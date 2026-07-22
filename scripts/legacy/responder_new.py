import json
import time
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Responder")

INPUT_FILE = "llm_input.txt"
OUTPUT_FILE = "llm_output.txt"

PLAN_RESPONSE = {
    "plan_name": "TicTacToe Calibration Plan",
    "tasks": [
        {
            "id": "T1",
            "description": "Implement core game logic in game.py",
            "dependencies": [],
            "expected_artifacts": [{"path": "game.py", "type": "CREATE"}],
            "acceptance_criteria": ["EXISTS:game.py", "CMD:python -c \"import game\""]
        },
        {
            "id": "T2",
            "description": "Implement CLI controller in cli.py",
            "dependencies": ["T1"],
            "expected_artifacts": [{"path": "cli.py", "type": "CREATE"}],
            "acceptance_criteria": ["EXISTS:cli.py", "CMD:python -c \"import cli\""]
        },
        {
            "id": "T3",
            "description": "Implement entry point in main.py",
            "dependencies": ["T2"],
            "expected_artifacts": [{"path": "main.py", "type": "CREATE"}],
            "acceptance_criteria": ["EXISTS:main.py", "CMD:python main.py"]
        }
    ]
}

T1_RESPONSE = {
    "artifacts": [
        {
            "path": "game.py",
            "content": "def initialize_board():\n    return [[' ' for _ in range(3)] for _ in range(3)]\n\ndef make_move(board, position, player):\n    row = (position - 1) // 3\n    col = (position - 1) % 3\n    if board[row][col] == ' ':\n        board[row][col] = player\n        return True\n    return False\n\ndef check_winner(board):\n    for row in board:\n        if row[0] == row[1] == row[2] != ' ':\n            return row[0]\n    for col in range(3):\n        if board[0][col] == board[1][col] == board[2][col] != ' ':\n            return board[0][col]\n    if board[0][0] == board[1][1] == board[2][2] != ' ':\n        return board[0][0]\n    if board[0][2] == board[1][1] == board[2][0] != ' ':\n        return board[0][2]\n    return None\n",
            "action": "CREATE"
        }
    ]
}

T2_RESPONSE = {
    "artifacts": [
        {
            "path": "cli.py",
            "content": "import game\n\ndef play_game(board):\n    pass\n",
            "action": "CREATE"
        }
    ]
}

T3_RESPONSE = {
    "artifacts": [
        {
            "path": "main.py",
            "content": "import game\nimport cli\n\ndef main():\n    board = game.initialize_board()\n    print(\"Player X wins\")\n\nif __name__ == '__main__':\n    main()\n",
            "action": "CREATE"
        }
    ]
}

def respond():
    logger.info("Responder started. Waiting for input...")
    while True:
        if os.path.exists(INPUT_FILE):
            try:
                with open(INPUT_FILE, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                
                if content:
                    # Read the input
                    data = json.loads(content)
                    user_prompt = data.get("user_prompt", "")
                    
                    response = None
                    
                    if "Planner" in user_prompt or "User Goal" in user_prompt:
                        logger.info("Detected Planner request.")
                        response = PLAN_RESPONSE
                    elif "Task ID: T1" in user_prompt:
                        logger.info("Detected T1 request.")
                        response = T1_RESPONSE
                    elif "Task ID: T2" in user_prompt:
                        logger.info("Detected T2 request.")
                        response = T2_RESPONSE
                    elif "Task ID: T3" in user_prompt:
                        logger.info("Detected T3 request.")
                        response = T3_RESPONSE
                    
                    if response:
                        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                            f.write(json.dumps(response, indent=2))
                        logger.info(f"Responded to request: {user_prompt[:50]}...")
                        
                        # Clear input to prevent double response
                        with open(INPUT_FILE, "w", encoding="utf-8") as f:
                            f.write("")
                    else:
                        logger.warning(f"Unrecognized prompt: {user_prompt[:50]}...")
                        # Clear input if we don't know what to do, otherwise it will loop
                        with open(INPUT_FILE, "w", encoding="utf-8") as f:
                            f.write("")

            except Exception as e:
                logger.error(f"Error processing input: {str(e)}")
        
        time.sleep(0.5)

if __name__ == "__main__":
    respond()
