import unittest
import os
import bcrypt
import socket
import threading
from unittest.mock import patch
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from server import main, handle_login, handle_register, ROOMS, game_start, handle_create, handle_join, update_board_status, process_place_command, handle_move

class TestServer(unittest.TestCase):
    passed_tests = 0
    failed_tests = 0

    temp_files = ["test_user_db.json"]

    @classmethod
    @patch('server.load_user_database')
    @patch('server.load_server_config')
    def setUpClass(cls, mock_load_server_config, mock_load_user_database):
        mock_load_server_config.return_value = {"port": 12345, "userDatabase": "test_user_db.json"}
        mock_load_user_database.return_value = [
            {"username": "testuser", "password": bcrypt.hashpw("testpass".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')}
        ]
        cls.server_thread = threading.Thread(target=main, args=('path_to_config.json',), daemon=True)
        cls.server_thread.start()

    def setUp(self):
        self.client_socket, self.server_socket = socket.socketpair()
        self.authenticated_clients = {}
        self.user_database = [
            {"username": "testuser", "password": bcrypt.hashpw("testpass".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')}
        ]

    def tearDown(self):
        self.client_socket.close()
        self.server_socket.close()
        ROOMS.clear()

    def track_result(self, success, test_name):
        if success:
            print(f"{test_name}: SUCCESS")
            TestServer.passed_tests += 1
        else:
            print(f"{test_name}: FAILURE")
            TestServer.failed_tests += 1

    def test_login_successful(self):
        test_name = "test_login_successful"
        try:
            message = "LOGIN:testuser:testpass"
            response = handle_login(message, self.client_socket, self.user_database, self.authenticated_clients)
            self.assertEqual(response, "LOGIN:ACKSTATUS:0\n")
            self.assertIn(self.client_socket, self.authenticated_clients)
            self.track_result(True, test_name)
        except AssertionError:
            self.track_result(False, test_name)

    def test_login_invalid_password(self):
        test_name = "test_login_invalid_password"
        try:
            message = "LOGIN:testuser:wrongpass"
            response = handle_login(message, self.client_socket, self.user_database, self.authenticated_clients)
            self.assertEqual(response, "LOGIN:ACKSTATUS:2\n")
            self.track_result(True, test_name)
        except AssertionError:
            self.track_result(False, test_name)

    def test_register_user_already_exists(self):
        test_name = "test_register_user_already_exists"
        try:
            message = "REGISTER:testuser:testpass"
            response = handle_register(message, self.user_database, 'test_user_db.json')
            self.assertEqual(response, "REGISTER:ACKSTATUS:1\n")  # User already exists
            self.track_result(True, test_name)
        except AssertionError:
            self.track_result(False, test_name)

    def test_register_successful(self):
        test_name = "test_register_successful"
        try:
            message = "REGISTER:newuser:newpass"
            response = handle_register(message, self.user_database, 'test_user_db.json')
            self.assertEqual(response, "REGISTER:ACKSTATUS:0\n")  # Registration successful
            self.track_result(True, test_name)
        except AssertionError:
            self.track_result(False, test_name)

    def test_room_creation(self):
        test_name = "test_room_creation"
        try:
            self.authenticated_clients[self.client_socket] = "testuser"
            message = "CREATE:room1"
            response = handle_create(message, self.client_socket, self.authenticated_clients)
            self.assertEqual(response, "CREATE:ACKSTATUS:0\n")
            self.assertIn("room1", ROOMS)
            self.track_result(True, test_name)
        except AssertionError:
            self.track_result(False, test_name)

    def test_room_creation_limit(self):
        test_name = "test_room_creation_limit"
        try:
            self.authenticated_clients[self.client_socket] = "testuser"
            for i in range(256):  # Create up to maximum room capacity
                room_name = f"room{i}"
                ROOMS[room_name] = {"players": [], "viewers": [], "move_queue": [], "status": "waiting"}
            response = handle_create("CREATE:room256", self.client_socket, self.authenticated_clients)
            self.assertEqual(response, "CREATE:ACKSTATUS:3\n")  # Max room limit reached
            self.track_result(True, test_name)
        except AssertionError:
            self.track_result(False, test_name)

    def test_join_as_player(self):
        test_name = "test_join_as_player"
        try:
            self.authenticated_clients[self.client_socket] = "testuser"
            ROOMS["room1"] = {"players": [], "viewers": [], "move_queue": [], "status": "waiting"}
            message = "JOIN:room1:PLAYER"
            response = handle_join(message, self.client_socket, self.authenticated_clients)
            self.assertEqual(response, "JOIN:ACKSTATUS:0\n")
            self.assertIn("testuser", ROOMS["room1"]["players"])
            self.track_result(True, test_name)
        except AssertionError:
            self.track_result(False, test_name)

    def test_join_as_viewer(self):
        test_name = "test_join_as_viewer"
        try:
            self.authenticated_clients[self.client_socket] = "testuser"
            ROOMS["room1"] = {"players": [], "viewers": [], "move_queue": [], "status": "waiting"}
            message = "JOIN:room1:VIEWER"
            response = handle_join(message, self.client_socket, self.authenticated_clients)
            self.assertEqual(response, "JOIN:ACKSTATUS:0\n")
            self.assertIn("testuser", ROOMS["room1"]["viewers"])
            self.track_result(True, test_name)
        except AssertionError:
            self.track_result(False, test_name)

    def test_game_start(self):
        test_name = "test_game_start"
        try:
            self.authenticated_clients[self.client_socket] = "player1"
            ROOMS["test_room"] = {
                "players": ["player1", "player2"],
                "viewers": [],
                "move_queue": [],
                "status": "waiting"
            }
            game_start("test_room", self.authenticated_clients)
            self.assertEqual(ROOMS["test_room"]["status"], "in-progress")
            self.track_result(True, test_name)
        except AssertionError:
            self.track_result(False, test_name)

    @patch('server.send_to_room')
    def test_board_status_update(self, mock_send_to_room):
        test_name = "test_board_status_update"
        try:
            # Set up the room with players and viewers, as expected by `update_board_status`
            ROOMS["test_room"] = {
                "players": ["player1", "player2"],
                "viewers": ["viewer1"],
                "board": [
                    ["", "", ""],
                    ["", "", ""],
                    ["", "", ""]
                ],
                "status": "in-progress"
            }

            # Simulate authenticated clients (mock sockets) as required by `send_to_room`
            self.authenticated_clients = {
                self.client_socket: "player1",
                self.server_socket: "viewer1"
            }

            # Call update_board_status, which should internally call `send_to_room`
            update_board_status("test_room", self.authenticated_clients)

            # Verify that `send_to_room` was called once
            mock_send_to_room.assert_called_once()

            # Check if the correct message format was sent to `send_to_room`
            sent_message = mock_send_to_room.call_args[0][1]
            self.assertTrue(sent_message.startswith("BOARDSTATUS:"))

            # Mark test as successful if no assertion errors
            print(f"{test_name}: SUCCESS")
            TestServer.passed_tests += 1
        except AssertionError:
            print(f"{test_name}: FAILURE")
            TestServer.failed_tests += 1
    @patch('server.send_to_room')
    def test_board_status_update_after_move(self, mock_send_to_room):
        test_name = "test_board_status_update_after_move"
        try:
            ROOMS["test_room"] = {
                "players": ["player1", "player2"],
                "viewers": ["viewer1"],
                "board": [
                    ["", "", ""],
                    ["", "", ""],
                    ["", "", ""]
                ],
                "status": "in-progress"
            }
            self.authenticated_clients = {
                self.client_socket: "player1",
                self.server_socket: "viewer1"
            }

            update_board_status("test_room", self.authenticated_clients)

            mock_send_to_room.assert_called_once()
            sent_message = mock_send_to_room.call_args[0][1]
            self.assertTrue(sent_message.startswith("BOARDSTATUS:"))
            print(f"{test_name}: SUCCESS")
            TestServer.passed_tests += 1
        except AssertionError:
            print(f"{test_name}: FAILURE")
            TestServer.failed_tests += 1

    # Test case for invalid board status message without crashing
    @patch('server.send_to_room')
    def test_board_status_invalid_message(self, mock_send_to_room):
        test_name = "test_board_status_invalid_message"
        try:
            ROOMS["test_room"] = {
                "players": ["player1", "player2"],
                "viewers": ["viewer1"],
                "board": [
                    ["X", "O", "X"],
                    ["O", "X", "O"],
                    ["O", "X", "O"]
                ],
                "status": "in-progress"
            }
            self.authenticated_clients = {
                self.client_socket: "player1",
                self.server_socket: "viewer1"
            }

            # Update the board status with an invalid message
            update_board_status("test_room", self.authenticated_clients)
            mock_send_to_room.assert_called_once()
            sent_message = mock_send_to_room.call_args[0][1]
            self.assertTrue(sent_message.startswith("BOARDSTATUS"))
            print(f"{test_name}: SUCCESS")
            TestServer.passed_tests += 1
        except AssertionError:
            print(f"{test_name}: FAILURE")
            TestServer.failed_tests += 1

    @classmethod
    def tearDownClass(cls):
        print(f"\nSummary: {cls.passed_tests}/{cls.passed_tests + cls.failed_tests} test cases passed")
        for file in cls.temp_files:
            if os.path.exists(file):
                os.remove(file)
                print(f"Removed temporary file: {file}")

if __name__ == "__main__":
    unittest.main()