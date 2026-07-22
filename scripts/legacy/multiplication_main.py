import sys

def main():
    if len(sys.argv) != 3:
        print("Usage: python main.py <num1> <num2>")
        sys.exit(1)
    
    try:
        num1 = float(sys.argv[1])
        num2 = float(sys.argv[2])
        print(num1 * num2)
    except ValueError:
        print("Error: Please provide two numbers.")
        sys.exit(1)

if __name__ == "__main__":
    main()
