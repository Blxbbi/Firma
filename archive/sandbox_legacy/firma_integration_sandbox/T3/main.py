import sys
import cli

if __name__ == "__main__":
    result = cli.run_game(sys.argv)
    if result:
        print(result)
