import asyncio
from time import perf_counter


async def delayed_task(
    name: str,
    delay: float,
    should_fail: bool = False,
) -> None:
    print(f"{name}start")
    await asyncio.sleep(delay)

    if should_fail:
        raise RuntimeError(f"{name} failed")

    print(f"{name}end")


async def main() -> None:
    started = perf_counter()
    try:
        await asyncio.wait_for(
            asyncio.gather(
                delayed_task("A", 1.0, should_fail=False),
                delayed_task("B", 2.0),
            ),
            timeout=1.5,
        )
    except TimeoutError:
        print("operation timed out")
    elapsed = perf_counter() - started
    print(f"elapsed:{elapsed:.2f}s")


asyncio.run(main())
