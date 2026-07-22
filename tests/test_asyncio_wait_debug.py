import asyncio
import time
import threading
import unittest

class TestAsyncioWait(unittest.TestCase):
    def test_wait_with_event(self):
        async def run_test():
            loop = asyncio.get_event_loop()
            event = asyncio.Event()
            wait_event = threading.Event()
            
            def blocking_wait():
                wait_event.wait()
                return 0
            
            proc_fut = loop.run_in_executor(None, blocking_wait)
            event_fut = asyncio.create_task(event.wait())
            
            async def set_event():
                await asyncio.sleep(0.1)
                event.set()
                wait_event.set()
            
            asyncio.create_task(set_event())
            
            start = time.time()
            done, pending = await asyncio.wait(
                [proc_fut, event_fut],
                return_when=asyncio.FIRST_COMPLETED,
            )
            elapsed = time.time() - start
            print(f"asyncio.wait returned after {elapsed:.2f}s")
            self.assertLess(elapsed, 1.0, "asyncio.wait should return quickly when event is set")
            
            for p in pending:
                p.cancel()
        
        asyncio.run(run_test())

if __name__ == "__main__":
    unittest.main()
