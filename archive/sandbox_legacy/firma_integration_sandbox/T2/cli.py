import game

def run_game(args=None):
    if args and "--test-sequence" in args:
        try:
            seq_index = args.index("--test-sequence")
            moves = args[seq_index+1:]
            board = game.initialize_board()
            player = "X"
            for move in moves:
                if not game.make_move(board, int(move), player):
                    return "Invalid Move"
                winner = game.check_winner(board)
                if winner:
                    return f"Player {winner} wins"
                player = "O" if player == "X" else "X"
            return "Draw"
        except Exception as e:
            return f"Error: {str(e)}"
    return None
