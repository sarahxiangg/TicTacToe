import socket
import selectors
import json
import os
import sys
import re
import game
import bcrypt

# Server configurations and constants
BUFFER_SIZE = 8192
MAX_ROOMS = 256
ROOMS = {}


# Setup selectors for managing non-blocking I/O
sel = selectors.DefaultSelector()

def game_start(room_name, authenticated_clients):
    """Initialize and handle the game loop for the room once two players have joined."""
    player1, player2 = ROOMS[room_name]["players"]
    ROOMS[room_name].update({
        "current_turn": player1,
        "awaiting_turn": player2,
        "board": game.create_board(),
        "status": "in-progress",
        "initial_queue_processed": False
    })

    send_to_room(room_name, f"BEGIN:{player1}:{player2}\n", authenticated_clients)
    send_to_viewers(room_name, f"INPROGRESS:{player1}:{player2}\n", authenticated_clients)

    # Process queued moves before the game officially starts
    if ROOMS[room_name]["move_queue"]:
        x, y, player = ROOMS[room_name]["move_queue"][0]
        ROOMS[room_name]["initial_queue_processed"] = True
        if player == ROOMS[room_name]["current_turn"]:
            ROOMS[room_name]["move_queue"].pop(0)
            if process_place_command(room_name, x, y, player, authenticated_clients):
                return  # End game if it finishes here
            swap_turns(room_name)
    
    ROOMS[room_name]["initial_queue_processed"] = True


    current_player_sock = next(sock for sock, user in authenticated_clients.items() if user == player1)
    try:
        sel.register(current_player_sock, selectors.EVENT_READ, lambda key: game_step(room_name, authenticated_clients, key))
    except KeyError:
        # If already registered, modify the existing registration to avoid KeyError
        sel.modify(current_player_sock, selectors.EVENT_READ, lambda key: game_step(room_name, authenticated_clients, key))


def game_step(room_name, authenticated_clients, key):
    """Handle a single turn step in the game without blocking the main event loop."""
    client_sock = key.fileobj

    # Check if the room still exists and is ongoing
    if room_name not in ROOMS or ROOMS[room_name].get("status") != "in-progress":
        return

    # Check for queued moves for the current turn
    if not ROOMS[room_name].get("initial_queue_processed"):
        while ROOMS[room_name]["move_queue"]:
            x, y, player = ROOMS[room_name]["move_queue"][0]  # Peek at the first queued move
            if player == ROOMS[room_name]["current_turn"]:
                # Process the move if it's the current player's turn
                ROOMS[room_name]["move_queue"].pop(0)  # Remove the move from the queue
                if process_place_command(room_name, x, y, player, authenticated_clients):
                    # End the game if this move finishes it
                    sel.unregister(client_sock)
                    ROOMS[room_name]["status"] = "ended"
                    return
                else:
                    swap_turns(room_name)  # Swap turns after a successful move
                    return  # Exit to wait for the next step in the main loop

    # Ensure it's the current player's turn if no queued moves are available
    if not is_current_player(client_sock, room_name, authenticated_clients):
        return

    # Regular handling if no queued moves
    data = receive_data(client_sock)
    if data:
        if handle_move(room_name, data, authenticated_clients):  # Game ends if True
            sel.unregister(client_sock)
            if room_name in ROOMS:  # Double-check room still exists
                ROOMS[room_name]["status"] = "ended"
        else:
            swap_turns(room_name)
            next_player = ROOMS[room_name]["current_turn"]
            next_sock = next(sock for sock, user in authenticated_clients.items() if user == next_player)
            sel.modify(next_sock, selectors.EVENT_READ, lambda key: game_step(room_name, authenticated_clients, key))
    else:
        handle_forfeit(room_name, authenticated_clients)
        sel.unregister(client_sock)
        if room_name in ROOMS:  # Double-check room still exists
            ROOMS[room_name]["status"] = "ended"




def is_current_player(client_sock, room_name, authenticated_clients):
    """Check if the client is the current player in the room."""
    return authenticated_clients.get(client_sock) == ROOMS[room_name]["current_turn"]

def receive_data(client_sock):
    """Receive and decode data from the client."""
    try:
        return client_sock.recv(BUFFER_SIZE).decode('ascii').strip()
    except (ConnectionResetError, BrokenPipeError):
        return None

def handle_move(room_name, data, authenticated_clients):
    """Process a PLACE command or handle a FORFEIT, and return True if game ends."""
    if data.startswith("PLACE"):
        _, x, y = data.split(":")
        x, y = int(x), int(y)
        return process_place_command(room_name, x, y, ROOMS[room_name]["current_turn"], authenticated_clients)
    elif data == "FORFEIT":
        handle_forfeit(room_name, authenticated_clients)
        return True
    return False


def swap_turns(room_name):
    """Swap the current turn to the other player."""
    ROOMS[room_name]["current_turn"], ROOMS[room_name]["awaiting_turn"] = ROOMS[room_name]["awaiting_turn"], ROOMS[room_name]["current_turn"]

# Board and move handling
def send_to_room(room_name, message, authenticated_clients):
    """Send a message to all players and viewers in a room."""
    for client in ROOMS[room_name]["players"] + ROOMS[room_name]["viewers"]:
        sock = next((s for s, user in authenticated_clients.items() if user == client), None)
        if sock:
            sock.send(message.encode('ascii'))

def send_to_viewers(room_name, message, authenticated_clients):
    """Send messages to only viewers in the room."""
    for client in ROOMS[room_name]["viewers"]:
        sock = next((s for s, user in authenticated_clients.items() if user == client), None)
        if sock:
            sock.send(message.encode('ascii'))

def update_board_status(room_name, authenticated_clients):
    """Send the current board status to all players and viewers in the room."""
    board_status = get_board_status(ROOMS[room_name]["board"])
    send_to_room(room_name, f"BOARDSTATUS:{board_status}\n", authenticated_clients)

def process_place_command(room_name, x, y, player, authenticated_clients):
    """Place a marker on the board and update the board status."""
    board = ROOMS[room_name]["board"]
    # Determine the correct marker based on the player
    if board[y][x] == game.EMPTY:
        marker = game.CROSS if player == ROOMS[room_name]["players"][0] else game.NOUGHT
        board[y][x] = marker
        
        # Check if the game has ended (win or draw)
        if game.player_wins(marker, board):
            send_to_room(room_name, f"GAMEEND:{get_board_status(board)}:0:{player}\n", authenticated_clients)
            del ROOMS[room_name]
            return True  # Game ends
        elif game.players_draw(board):
            send_to_room(room_name, f"GAMEEND:{get_board_status(board)}:1\n", authenticated_clients)
            del ROOMS[room_name]
            return True  # Game ends
        if ROOMS[room_name]["initial_queue_processed"]:
            update_board_status(room_name, authenticated_clients)
    return False  # Game continues


def handle_forfeit(room_name, authenticated_clients):
    """Handle game forfeiture by a player."""
    forfeiting_player = ROOMS[room_name]["current_turn"]
    winning_player = ROOMS[room_name]["awaiting_turn"]
    board_status = get_board_status(ROOMS[room_name]["board"])
    send_to_room(room_name, f"GAMEEND:{board_status}:2:{winning_player}\n", authenticated_clients)
    del ROOMS[room_name]

# Helper functions for game board status
def get_board_status(board):
    """Return the board status as a string for communication."""
    return ''.join(['1' if cell == game.CROSS else '2' if cell == game.NOUGHT else '0' for row in board for cell in row])

def send_to_viewers(room_name, message, authenticated_clients):
    """Send messages to only viewers in the room """""
    for client in ROOMS[room_name]["viewers"]:
        sock = next((s for s, user in authenticated_clients.items() if user == client), None)
        if sock:
            sock.send(message.encode('ascii'))


def load_user_database(user_db_path):
    try:
        with open(os.path.expanduser(user_db_path), 'r') as db_file:
            user_database = json.load(db_file)
            if not isinstance(user_database, list):
                raise ValueError("Error: User database is not a JSON array.")
            for record in user_database:
                if not all(key in record for key in ("username", "password")):
                    raise ValueError("Error: User database contains invalid user record formats.")
        return user_database
    except FileNotFoundError:
        raise RuntimeError(f"Error: {user_db_path} doesn’t exist.")
    except json.JSONDecodeError:
        raise RuntimeError(f"Error: {user_db_path} is not in a valid JSON format.")

def save_user_database(user_db_path, user_database):
    with open(os.path.expanduser(user_db_path), 'w') as db_file:
        json.dump(user_database, db_file)

def load_server_config(config_path):
    try:
        with open(config_path, 'r') as config_file:
            config = json.load(config_file)

        missing_keys = [key for key in ["port", "userDatabase"] if key not in config]
        if missing_keys:
            missing_keys_str = ", ".join(missing_keys)
            raise RuntimeError(f"Error: {config_path} missing key(s): {missing_keys_str}")

        port = config["port"]
        if not isinstance(port, int) or not (1024 <= port <= 65535):
            raise RuntimeError("Error: port number out of range")

        return config
    except FileNotFoundError:
        raise RuntimeError(f"Error: {config_path} doesn’t exist.")
    except json.JSONDecodeError:
        raise RuntimeError(f"Error: {config_path} is not in a valid JSON format.")

def handle_login(message, client_sock, user_database, authenticated_clients):
    try:
        _, username, password = message.split(':')
        user = next((u for u in user_database if u['username'] == username), None)
        if not user:
            return "LOGIN:ACKSTATUS:1\n"  # User not found

        if bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            authenticated_clients[client_sock] = username
            return "LOGIN:ACKSTATUS:0\n"  # Successful login
        return "LOGIN:ACKSTATUS:2\n"  # Incorrect password
    except ValueError:
        return "LOGIN:ACKSTATUS:3\n"  # Invalid format

def handle_register(message, user_database, user_db_path):
    try:
        _, username, password = message.split(':')
        if len(username) > 20 or len(password) > 20:
            return "REGISTER:ACKSTATUS:2\n"

        if next((u for u in user_database if u['username'] == username), None):
            return "REGISTER:ACKSTATUS:1\n"  # User already exists

        hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        user_database.append({"username": username, "password": hashed_pw})
        save_user_database(user_db_path, user_database)
        return "REGISTER:ACKSTATUS:0\n"  # Registration successful
    except ValueError:
        return "REGISTER:ACKSTATUS:2\n"  # Invalid format

def handle_roomlist(message):
    try:
        _, mode = message.split(':')
    except ValueError:
        return "ROOMLIST:ACKSTATUS:1"

    if mode not in ["PLAYER", "VIEWER"]:
        return "ROOMLIST:ACKSTATUS:1\n"

    room_list = ",".join(sorted(ROOMS.keys()))
    return f"ROOMLIST:ACKSTATUS:0:{room_list}\n"

def handle_create(message, client_sock, authenticated_clients):
    try:
        _, room_name = message.split(":")
    except ValueError:
        return "CREATE:ACKSTATUS:4\n"

    if not re.match(r'^[a-zA-Z0-9_ -]{1,20}$', room_name):
        return "CREATE:ACKSTATUS:1\n"

    if room_name in ROOMS:
        return "CREATE:ACKSTATUS:2\n"

    if len(ROOMS) >= MAX_ROOMS:
        return "CREATE:ACKSTATUS:3\n"

    ROOMS[room_name] = {"players": [], "viewers": [], "move_queue": [], "status": "waiting"}  # Set initial status
    username = authenticated_clients[client_sock]
    ROOMS[room_name]["players"].append(username)
    if len(ROOMS[room_name]["players"]) == 2:
        #player1, player2 = ROOMS[room_name]["players"]
        msg = "CREATE:ACKSTATUS:0\n"
        client_sock.send(msg.encode('ascii'))
        return
    return "CREATE:ACKSTATUS:0\n"

def handle_join(message, client_sock, authenticated_clients):
    try:
        _, room_name, mode = message.split(":")

        if room_name not in ROOMS:
            return "JOIN:ACKSTATUS:1\n"
        if mode not in ["PLAYER", "VIEWER"]:
            return "JOIN:ACKSTATUS:3\n"

        username = authenticated_clients[client_sock]
        if mode == "PLAYER":
            if len(ROOMS[room_name]["players"]) >= 2:
                return "JOIN:ACKSTATUS:2\n"  # Room full

            ROOMS[room_name]["players"].append(username)
            
            # Send "BEGIN:<player1>:<player2>" message if two players are in the room
            if len(ROOMS[room_name]["players"]) == 2:
                player1, player2 = ROOMS[room_name]["players"]
                msg = f"JOIN:ACKSTATUS:0\n"
                client_sock.send(msg.encode('ascii'))

                return "GAME READY"
        
        elif mode == "VIEWER":
            # Add viewer to the room's viewers list
            ROOMS[room_name]["viewers"].append(username)

            if ROOMS[room_name].get("status") == "in-progress":
                players = ":".join(ROOMS[room_name]["players"])
                client_sock.send(f"JOIN:ACKSTATUS:0\nINPROGRESS:{players}\n".encode('ascii'))
                return None

        return "JOIN:ACKSTATUS:0\n"
    except ValueError:
        return "JOIN:ACKSTATUS:3\n"  # Invalid message format




def close_connection(client_sock, authenticated_clients):
    sel.unregister(client_sock)
    authenticated_clients.pop(client_sock, None)
    client_sock.close()


def accept_client(server_sock):
    client_sock, _ = server_sock.accept()
    client_sock.setblocking(False)
    sel.register(client_sock, selectors.EVENT_READ, handle_client)

def handle_client(key, authenticated_clients, user_database, user_db_path):
    client_sock = key.fileobj
    try:
        data = client_sock.recv(BUFFER_SIZE)
        if not data:
            close_connection(client_sock, authenticated_clients)
            return

        message = data.decode('ascii').strip()

        # Check if message requires authentication
        if message.startswith("REGISTER"):
            response = handle_register(message, user_database, user_db_path)
        elif message.startswith("LOGIN"):
            response = handle_login(message, client_sock, user_database, authenticated_clients)
        elif authenticated_clients.get(client_sock) is None:
            response = "BADAUTH\n"
        elif message.startswith("ROOMLIST"):
            response = handle_roomlist(message)
        elif message.startswith("CREATE"):
            response = handle_create(message, client_sock, authenticated_clients)
            if response == "GAME READY": 
                _, room_name, _ = message.split(":")
                game_start(room_name, authenticated_clients)
                response = None
        elif message.startswith("JOIN"):
            response = handle_join(message, client_sock, authenticated_clients)
            if response == "GAME READY": 
                _, room_name, _ = message.split(":")
                game_start(room_name, authenticated_clients)
                response = None
        elif not any(authenticated_clients.get(client_sock) in room["players"] for room in ROOMS.values()):
            response = "NOROOM\n"
        
        elif message.startswith("PLACE"):
            room_name = next((room for room, details in ROOMS.items() if authenticated_clients[client_sock] in details["players"]), None)
            if room_name:
                _, x, y = message.split(":")
                x, y = int(x), int(y)
                
                if ROOMS[room_name]["status"] != "in-progress" or len(ROOMS[room_name]["players"]) < 2:
                    # Queue the move if the game hasn't started or only one player has joined
                    ROOMS[room_name]["move_queue"].append((x, y, authenticated_clients[client_sock]))
                elif ROOMS[room_name]["current_turn"] != authenticated_clients[client_sock]:
                    # Queue the move if it's not the player's turn
                    ROOMS[room_name]["move_queue"].append((x, y, authenticated_clients[client_sock]))
                else:
                    # Process the move if it's the player's turn and the game is in progress
                    end = handle_move(room_name, message, authenticated_clients)
                    if end:
                        # If the game ends, mark it as ended
                        ROOMS[room_name]["status"] = "ended"
                    else:
                        swap_turns(room_name)
            response = None


        else:
            response = None

        if response:
            client_sock.send(response.encode('ascii'))
    except (ConnectionResetError, BrokenPipeError):
        close_connection(client_sock, authenticated_clients)


def main(config_path):
    try:
        config = load_server_config(config_path)
        port = config["port"]
        user_db_path = config["userDatabase"]

        user_database = load_user_database(user_db_path)
        authenticated_clients = {}

        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        server_sock.bind(('0.0.0.0', port))
        server_sock.listen(100)
        server_sock.setblocking(False)
        sel.register(server_sock, selectors.EVENT_READ, lambda key: accept_client(key.fileobj))

        while True:
            events = sel.select()
            for key, _ in events:
                if key.data is handle_client:
                    handle_client(key, authenticated_clients, user_database, user_db_path)
                else:
                    key.data(key)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Error: Expecting 1 argument: <server config path>.", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])