from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from caddsuite.contracts.execution import GPUInfo, ResourceCapacity, ResourceRequest
from caddsuite.execution.resources import ResourceScheduler


def _request(
    cpu: int = 1,
    memory: int = 1024,
    gpu_count: int = 0,
    gpu_memory: int | None = None,
) -> ResourceRequest:
    return ResourceRequest(
        cpu_cores=cpu,
        memory_MiB=memory,
        gpu_count=gpu_count,
        gpu_memory_MiB_per_gpu=gpu_memory,
    )


def test_cpu_and_memory_capacity_are_not_oversubscribed() -> None:
    scheduler = ResourceScheduler(ResourceCapacity(cpu_cores=4, memory_MiB=8000))
    first = scheduler.try_acquire("task-1", _request(cpu=3, memory=6000))
    assert first.admitted
    cpu_block = scheduler.try_acquire("task-2", _request(cpu=2))
    assert not cpu_block.admitted
    assert cpu_block.reason == "insufficient CPU cores"
    memory_block = scheduler.try_acquire("task-3", _request(memory=3000))
    assert not memory_block.admitted
    assert memory_block.reason == "insufficient host memory"


def test_gpu_reservations_are_exclusive_and_honor_device_memory() -> None:
    scheduler = ResourceScheduler(
        ResourceCapacity(
            cpu_cores=8,
            memory_MiB=32000,
            gpus=(
                GPUInfo(index=0, name="GPU-A", memory_MiB=8192),
                GPUInfo(index=1, name="GPU-B", memory_MiB=4096),
            ),
        )
    )
    first = scheduler.try_acquire("gpu-task-1", _request(gpu_count=1, gpu_memory=6000))
    assert first.admitted
    assert first.lease is not None
    assert first.lease.gpu_indices == (0,)
    blocked = scheduler.try_acquire("gpu-task-2", _request(gpu_count=1, gpu_memory=6000))
    assert not blocked.admitted
    assert blocked.reason == "no available GPU meets the requested memory"
    assert scheduler.release("gpu-task-1")
    next_lease = scheduler.try_acquire("gpu-task-2", _request(gpu_count=1, gpu_memory=6000))
    assert next_lease.admitted
    assert next_lease.lease is not None
    assert next_lease.lease.gpu_indices == (0,)


def test_unknown_gpu_memory_cannot_satisfy_a_minimum_request() -> None:
    scheduler = ResourceScheduler(
        ResourceCapacity(
            cpu_cores=4,
            memory_MiB=12000,
            gpus=(GPUInfo(index=0, name="unreported-memory"),),
        )
    )
    result = scheduler.try_acquire("task", _request(gpu_count=1, gpu_memory=1024))
    assert not result.admitted
    assert result.reason == "no available GPU meets the requested memory"


def test_release_is_idempotent_and_duplicate_task_cannot_double_reserve() -> None:
    scheduler = ResourceScheduler(ResourceCapacity(cpu_cores=2, memory_MiB=2000))
    assert scheduler.try_acquire("same", _request()).admitted
    duplicate = scheduler.try_acquire("same", _request())
    assert not duplicate.admitted
    assert "already holds" in (duplicate.reason or "")
    assert scheduler.release("same")
    assert not scheduler.release("same")


def test_concurrent_admission_is_atomic() -> None:
    scheduler = ResourceScheduler(ResourceCapacity(cpu_cores=2, memory_MiB=8000))

    def acquire(index: int) -> bool:
        return scheduler.try_acquire(f"task-{index}", _request()).admitted

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(acquire, range(8)))
    assert sum(outcomes) == 2
    assert len(scheduler.active_leases()) == 2


def test_invalid_resource_requests_are_rejected_by_schema() -> None:
    with pytest.raises(ValidationError):
        ResourceRequest(cpu_cores=0, memory_MiB=1024)
    with pytest.raises(ValidationError, match="requires gpu_count"):
        ResourceRequest(cpu_cores=1, memory_MiB=1024, gpu_memory_MiB_per_gpu=512)
