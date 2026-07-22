import asyncio
import time
import unittest

class TestAsyncioRun(unittest.TestCase):
    def test_asyncio_run_in_unittest(self):
        async def run_test():
            await asyncio.sleep(0.1)
            return 42
        
        start = time.time()
        result = asyncio.run(run_test())
        elapsed = time.time() - start
        print(f"asyncio.run finished after {elapsed:.2f}s, result={result}")
        self.assertEqual(result, 42)
        self.assertLess(elapsed, 1.0)

if __name__ == "__main__":
    unittest.main()
