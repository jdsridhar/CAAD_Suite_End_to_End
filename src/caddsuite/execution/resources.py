"""Atomic in-process CPU, host-memory, and exclusive-GPU admission."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from caddsuite.contracts.execution import ResourceCapacity, ResourceRequest


@dataclass(frozen=True, slots=True)
class ResourceLease:
    task_id: str
    request: ResourceRequest
    gpu_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    lease: ResourceLease | None
    reason: str | None

    @property
    def admitted(self) -> bool:
        return self.lease is not None


class ResourceScheduler:
    """Reserve configured resources without oversubscription.

    Reservations are process-local and intentionally small for the local executor. On restart,
    orchestration must reconcile live tasks before creating new leases; a future remote/HPC
    scheduler will implement the same admission port against its own resource manager.
    """

    def __init__(self, capacity: ResourceCapacity) -> None:
        self._capacity = capacity
        self._leases: dict[str, ResourceLease] = {}
        self._lock = RLock()

    def try_acquire(self, task_id: str, request: ResourceRequest) -> AdmissionResult:
        if not task_id.strip():
            raise ValueError("task_id must not be blank")
        with self._lock:
            if task_id in self._leases:
                return AdmissionResult(None, f"task {task_id!r} already holds a resource lease")

            used_cpu = sum(lease.request.cpu_cores for lease in self._leases.values())
            used_memory = sum(lease.request.memory_MiB for lease in self._leases.values())
            if used_cpu + request.cpu_cores > self._capacity.cpu_cores:
                return AdmissionResult(None, "insufficient CPU cores")
            if used_memory + request.memory_MiB > self._capacity.memory_MiB:
                return AdmissionResult(None, "insufficient host memory")

            reserved_gpu_ids = {
                gpu_id for lease in self._leases.values() for gpu_id in lease.gpu_indices
            }
            eligible_gpu_ids = tuple(
                gpu.index
                for gpu in self._capacity.gpus
                if gpu.index not in reserved_gpu_ids
                and (
                    request.gpu_memory_MiB_per_gpu is None
                    or (
                        gpu.memory_MiB is not None
                        and gpu.memory_MiB >= request.gpu_memory_MiB_per_gpu
                    )
                )
            )
            if len(eligible_gpu_ids) < request.gpu_count:
                if len(self._capacity.gpus) - len(reserved_gpu_ids) < request.gpu_count:
                    reason = "insufficient unreserved GPUs"
                else:
                    reason = "no available GPU meets the requested memory"
                return AdmissionResult(None, reason)

            lease = ResourceLease(
                task_id=task_id,
                request=request,
                gpu_indices=eligible_gpu_ids[: request.gpu_count],
            )
            self._leases[task_id] = lease
            return AdmissionResult(lease, None)

    def release(self, task_id: str) -> bool:
        """Release a task's lease; False means it was already absent (idempotent cleanup)."""
        with self._lock:
            return self._leases.pop(task_id, None) is not None

    def active_leases(self) -> tuple[ResourceLease, ...]:
        with self._lock:
            return tuple(self._leases.values())
