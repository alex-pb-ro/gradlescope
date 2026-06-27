# Parallel execution

Parallel execution lets independent projects configure and run concurrently. In
a monorepo with hundreds of modules this is one of the highest-leverage flags.

## Enable it

In `gradle.properties`:

```
org.gradle.parallel=true
org.gradle.workers.max=8            # tune to CI/dev core counts
org.gradle.caching=true
```

## Make it effective

- Parallelism is bounded by the dependency graph. A deep or tangled graph
  serializes the build — see the untangle-dependency-graph runbook.
- Ensure tasks declare correct inputs/outputs so Gradle can safely schedule
  them; hidden inter-project file dependencies break parallel correctness.
- Combine with the configuration cache and (eventually) Isolated Projects for
  parallel *configuration*, not just execution.

## Validate

```
./gradlew build --parallel --profile   # open the generated profile report
```

## References

- [Parallel execution](https://docs.gradle.org/current/userguide/performance.html#parallel_execution)
