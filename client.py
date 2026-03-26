import socket
import sys
import selectors
import game

BUFFER_SIZE = 8192
sel = selectors.DefaultSelector()

class GameState:
    def __init__(self):
        self.username = ""
        self.current_turn_player = ""
        self.opposing_player = ""
        self.is_player = False
        self.game_started = False
        self.board = [["0"] * 3 for _ in range(3)]

def handle_inprogress(message, state):
    _, state.current_turn_player, state.opposing_player = message.split(":")
    print(f"Match between {state.current_turn_player} and {state.opposing_player} is currently in progress, it is {state.current_turn_player}'s turn")

def handle_boardstatus(message, state):
    board_status = message.split(":")[1]
    print(f"Current board status: {board_status}")
    game.print_board(board_status)
    state.board = [[board_status[i*3 + j] for j in range(3)] for i in range(3)]
    
    if state.is_player:
        if state.username == state.current_turn_player:
            print(f"It is {state.opposing_player}'s turn.")
        else:
            print(f"It is your turn.")
    else:
        print(f"It is {state.current_turn_player}'s turn.")

def send_place_command(sock, x, y):
    message = f"PLACE:{x}:{y}\n"
    sock.sendall(message.encode('ascii'))

def send_forfeit_command(sock):
    message = "FORFEIT\n"
    sock.sendall(message.encode('ascii'))

def handle_gameend(message, state):
    parts = message.split(":")
    board_status = parts[1]
    status_code = int(parts[2])
    
    print(f"Final board status: {board_status}")
    game.print_board(board_status)
    
    if status_code == 0:
        winner = parts[3]
        if state.is_player:
            if state.username == winner:
                print("Congratulations, you won!")
            else:
                print("Sorry you lost. Good luck next time.")
        else:
            print(f"{winner} has won this game.")
    elif status_code == 1:
        print("Game ended in a draw.")
    elif status_code == 2:
        winner = parts[3]
        print(f"{winner} won due to the opposing player forfeiting.")

def send_message(sock, message):
    message_with_newline = message + '\n'
    sock.sendall(message_with_newline.encode('ascii'))

def receive_message(sock):
    data = sock.recv(BUFFER_SIZE).decode('ascii')
    messages = data.split('\n')
    return [msg for msg in messages if msg]

def login(sock, state):
    username = input("Enter username: ")
    password = input("Enter password: ")
    send_message(sock, f"LOGIN:{username}:{password}")

    response = receive_message(sock)
    for msg in response:
        if msg == "LOGIN:ACKSTATUS:0":
            print(f"Welcome {username}")
            state.username = username
            return True
        elif msg == "LOGIN:ACKSTATUS:1":
            print(f"Error: User {username} not found", file=sys.stderr)
        elif msg == "LOGIN:ACKSTATUS:2":
            print(f"Error: Wrong password for user {username}", file=sys.stderr)
        elif msg == "LOGIN:ACKSTATUS:3":
            print("Error: Invalid login format", file=sys.stderr)
    return False

def register(sock):
    username = input("Enter username: ")
    password = input("Enter password: ")
    send_message(sock, f"REGISTER:{username}:{password}")

    response = receive_message(sock)
    for msg in response:
        if msg == "REGISTER:ACKSTATUS:0":
            print(f"Successfully created user account {username}")
        elif msg == "REGISTER:ACKSTATUS:1":
            print(f"Error: User {username} already exists", file=sys.stderr)
        elif msg == "REGISTER:ACKSTATUS:2":
            print("Error: Invalid registration format", file=sys.stderr)

def roomlist(sock, mode):
    send_message(sock, f"ROOMLIST:{mode}")

    response = receive_message(sock)
    for msg in response:
        if msg.startswith("ROOMLIST:ACKSTATUS:0:"):
            room_list = msg.split(":", 3)[-1]
            print(f"Rooms available to join as {mode}: {room_list}")
        elif msg == "ROOMLIST:ACKSTATUS:1":
            print("Error: Please input a valid mode.", file=sys.stderr)

def create_room(sock, room_name, state):
    send_message(sock, f"CREATE:{room_name}")

    response = receive_message(sock)
    for msg in response:
        if msg == "CREATE:ACKSTATUS:0":
            print(f"Successfully created room {room_name}")
            print("Waiting for other player...")
            state.is_player = True
            return
        elif msg == "CREATE:ACKSTATUS:1":
            print(f"Error: Room {room_name} is invalid", file=sys.stderr)
        elif msg == "CREATE:ACKSTATUS:2":
            print(f"Error: Room {room_name} already exists", file=sys.stderr)
        elif msg == "CREATE:ACKSTATUS:3":
            print("Error: Server already contains a maximum of 256 rooms", file=sys.stderr)
        elif msg == "BADAUTH":
            print("Error: You must be logged in to perform this action.", file=sys.stderr)

def join(sock, room_name, mode, state):
    send_message(sock, f"JOIN:{room_name}:{mode}")

    response = receive_message(sock)
    for msg in response:
        if msg == "JOIN:ACKSTATUS:0":
            print(f"Successfully joined room {room_name} as a {mode}")
            state.is_player = mode == "PLAYER"
        elif msg == "JOIN:ACKSTATUS:1":
            print(f"Error: No room named {room_name}", file=sys.stderr)
        elif msg == "JOIN:ACKSTATUS:2":
            print(f"Error: The room {room_name} already has 2 players", file=sys.stderr)
        elif msg == "JOIN:ACKSTATUS:3":
            print("Error: Invalid join format or mode.", file=sys.stderr)
        elif msg == "BADAUTH":
            print("Error: You must be logged in to perform this action.", file=sys.stderr)
        elif msg.startswith("BEGIN"):
            _, player1, player2 = msg.split(":")
            state.current_turn_player, state.opposing_player = player1, player2
            state.is_player = state.username in {state.current_turn_player, state.opposing_player}
            print(f"Game has started between {player1} and {player2}")

def handle_input(sock, state):
    try:
        command = input().strip().upper()
    except EOFError:
        # EOF reached; set a timeout to allow remaining server messages to be received
        print("EOF received. Waiting to receive remaining messages from server...")
        eof_wait(sock, state)
        return

    if command == "LOGIN":
        login(sock, state)
    elif command == "REGISTER":
        register(sock)
    elif command == "ROOMLIST":
        mode = input("Enter mode (PLAYER, VIEWER): ").upper()
        roomlist(sock, mode)
    elif command == "CREATE":
        room_name = input("Enter room name you want to create: ")
        create_room(sock, room_name,state)
    elif command == "JOIN":
        room_name = input("Enter room name you want to join: ")
        mode = input("You wish to join the room as: (PLAYER, VIEWER): ").upper()
        join(sock, room_name, mode, state)
    elif command == "PLACE":
        while True:
            try:
                x = int(input("Enter x-coordinate: "))
                if x < 0 or x > 2:
                    print("Invalid x-coordinate. Please enter a value between 0 and 2.")
                    continue

                y = int(input("Enter y-coordinate: "))
                if y < 0 or y > 2:
                    print("Invalid y-coordinate. Please enter a value between 0 and 2.")
                    continue
                if state.board[y][x] != "0":
                    print("Error: Cell already occupied. Please choose an empty cell.")
                    continue
                break
            except ValueError:
                print("Invalid input. Please enter integer values for coordinates.")
        send_place_command(sock, x, y)

    elif command == "FORFEIT":
        if state.is_player:
            send_forfeit_command(sock)
        else:
            print("You must be a player to forfeit the game.")
    elif command == "QUIT":
        print("Disconnecting from server...")
        sel.unregister(sys.stdin)
        sel.unregister(sock)
        sock.close()
        sys.exit(0)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
def eof_wait(sock, state):
    sock.settimeout(1)  # Set a 1-second timeout
    try:
        while True:
            response = receive_message(sock)
            if not response:
                break  # No more messages; exit
            for msg in response:
                if msg.startswith("GAMEEND:"):
                    handle_gameend(msg, state)
                    return  # Exit after handling GAMEEND
    except socket.timeout:
        # Timeout reached without receiving GAMEEND
        print("No more messages from server. Exiting.")
    finally:
        sock.settimeout(None)  # Reset timeout to default
        sock.close()
        sys.exit(0)

def handle_server_message(sock, state):
    response = receive_message(sock)
    for msg in response:
        if msg == "NOROOM":
            print("Error: You must join a room to place a marker.")
        elif msg.startswith("INPROGRESS:"):
            handle_inprogress(msg,state)
        elif msg.startswith("BOARDSTATUS:"):
            handle_boardstatus(msg, state)
        elif msg.startswith("GAMEEND:"):
            handle_gameend(msg, state)
        elif msg.startswith("BEGIN:"):
            _, player1, player2 = msg.split(":")
            state.current_turn_player, state.opposing_player = player1, player2
            state.is_player = state.username in {state.current_turn_player, state.opposing_player}
            state.game_started = True
            print(f"Game has started between {player1} and {player2}")

def main(args):
    if len(args) != 2:
        print("Error: Expecting 2 arguments: <server address> <port>", file=sys.stderr)
        sys.exit(1)

    server_address = args[0]
    try:
        port = int(args[1])
    except ValueError:
        print("Error: Port should be an integer.", file=sys.stderr)
        sys.exit(1)
    
    state = GameState()

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((server_address, port))
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        sel.register(sock, selectors.EVENT_READ, lambda key: handle_server_message(sock, state))
        sel.register(sys.stdin, selectors.EVENT_READ, lambda key: handle_input(sock, state))

        while True:
            events = sel.select()
            for key, _ in events:
                callback = key.data
                callback(key.fileobj)  # Execute the appropriate handler function

    except ConnectionError:
            print(f"Error: cannot connect to server at {server_address}:{port}.", file=sys.stderr)
    finally:
        sock.close()
        sel.close()

if __name__ == "__main__":
    main(sys.argv[1:])