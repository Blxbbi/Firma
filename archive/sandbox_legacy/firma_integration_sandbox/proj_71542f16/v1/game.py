def initialize_board():
    return [[' ' for _ in range(3)] for _ in range(3)]

def make_move(board, position, player):
    row = (position - 1) // 3
    col = (position - 1) % 3
    if board[row][col] == ' ':
        board[row][col] = player
        return True
    return False

def check_winner(board):
    for row in board:
        if row[0] == row[1] == row[2] != ' ':
            return row[0]
    for col in range(3):
        if board[0][col] == board[1][col] == board[2][col] != ' ':
            return board[0][col]
    if board[0][0] == board[1][1] == board[2][2] != ' ':
        return board[0][0]
    if board[0][2] == board[1][1] == board[2][0] != ' ':
        return board[0][2]
    return None
