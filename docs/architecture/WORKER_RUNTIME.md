# Isolated worker runtime

The application core and scientific engines often need different Python environments. The worker package is therefore standard-library-only; an engine worker may import its own engine but does not import Pydantic, SQLAlchemy, or caddsuite core modules.

## Task and result boundary

The common task envelope contains protocol version, stable task ID, operation, and an engine-specific JSON payload. The adapter writes and hash-links the request artifact, then launches the worker as an argv list with shell disabled. The worker rejects malformed or duplicate-key JSON, NaN/Infinity, unsupported protocol versions, malformed task IDs, and the wrong operation.

A worker handler returns a JSON object. The runtime wraps it in a result with completed status, task/operation identity, start/end timestamps, and elapsed wall time. Expected failures use stable codes and an explicit retryable flag. Unexpected failures are marked non-retryable and their traceback goes to stderr. Both result and stderr are retained by the local executor.

The runtime writes events as newline-delimited JSON. Each event has a sequence, UTC timestamp, type, message, and structured data. This supports live progress without parsing engine-specific terminal output. Event data and result data must be strict JSON with finite numbers. Result files use an atomic same-directory write, and a worker refuses to overwrite a previous result or event stream.

## Why this boundary exists

A molecular calculation may require Psi4's Python 3.10 environment while the platform uses a newer Python and its own dependencies. Plain JSON allows the adapter to pass a normalized request without loading the engine in the UI or core process. The adapter still owns scientific validation and converts the worker response into a versioned domain result; this runtime does not claim that JSON alone makes different engines scientifically interchangeable.

For interviews, describe this as a process boundary with a small wire protocol: the contract preserves identity and provenance across runtimes, and the adapter translates between platform models and engine-native behavior. It is smaller than a network API, but gives the same explicit request/response discipline for a local process.
