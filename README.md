# 🎮 Tic-Tac-Toe Multiplayer System

I built this project as a fully functional **client-server Tic-Tac-Toe system** with authentication, game rooms, and real-time gameplay. The goal was to go beyond a simple game and actually understand how **networked systems, concurrency, and state management** work in practice.

---

## 🚀 What This Does

It’s a **real-time multiplayer system** where:

* Multiple users can connect to a server
* Players can create and join game rooms
* Two players compete while others can watch live
* The server enforces game rules and synchronises state

Everything runs over **TCP sockets with non-blocking I/O**, so multiple clients can interact concurrently .

---

## 🧠 Why I Built This

I wanted to properly understand:

* How real systems handle **multiple clients at once**
* How to design a **server-authoritative architecture**
* How to deal with **edge cases** like out-of-turn moves and disconnects
* How to structure clean communication protocols between client and server

Instead of just learning theory, this forced me to deal with the messy reality of systems programming.

---

## 🏗️ Architecture

```
Client (CLI)  <----TCP---->  Server  <---->  Game Logic
```

* **Server**

  * Handles authentication, rooms, and game state
  * Controls all logic (source of truth)

* **Client**

  * Sends commands and displays updates
  * Lightweight, event-driven

* **Game Engine**

  * Handles board logic, win/draw detection

---

## 📂 Project Structure

```
server.py       → core server + networking logic
client.py       → interactive CLI client
game.py         → Tic-Tac-Toe rules and board logic
tictactoe.py    → standalone local version
test.py         → unit tests
```

* Server manages everything from **rooms → turns → win conditions** 
* Game logic is cleanly separated and reusable 

---

## 🔐 Features

### 👤 Authentication

* Register + login system
* Passwords hashed using bcrypt
* JSON-based user database

### 🏠 Rooms

* Create rooms (up to 256)
* Join as:

  * PLAYER (max 2)
  * VIEWER (spectate live)
* List all active rooms

### ⚔️ Gameplay

* Turn-based Tic-Tac-Toe
* Real-time board updates
* Win / draw / forfeit detection
* Move queue (handles early + invalid timing moves)

### 🌐 Networking

* Non-blocking I/O using `selectors`
* Handles multiple clients concurrently
* Robust to disconnects and invalid inputs

---

## ▶️ How to Run

### 1. Start the Server

```bash
python server.py config.json
```

Example config:

```json
{
  "port": 12345,
  "userDatabase": "users.json"
}
```

---

### 2. Start a Client

```bash
python client.py 127.0.0.1 12345
```

---

## 🎮 Commands (Client Side)

```
LOGIN
REGISTER
ROOMLIST
CREATE
JOIN
PLACE
FORFEIT
QUIT
```

### Typical Flow

1. Register / login
2. Create or join a room
3. Wait for second player
4. Game starts automatically
5. Play using `PLACE`

---

## 📡 Protocol 
Some key messages:

```
LOGIN:ACKSTATUS:<code>
CREATE:ACKSTATUS:<code>
JOIN:ACKSTATUS:<code>
BEGIN:<player1>:<player2>
BOARDSTATUS:<state>
GAMEEND:<state>:<result>
```

The server always controls the state and broadcasts updates.

---

## 🧩 Game Logic

* 3x3 board
* Representation:

  * `0` → empty
  * `1` → X
  * `2` → O
* Win conditions:

  * rows, columns, diagonals
* Draw = full board, no winner 

---

## 🧪 Testing

```bash
python test.py
```

Covers:

* Authentication
* Room creation/joining
* Game start + board updates

---

## ⚙️ Design Choices 

### Server 

The server is the **single source of truth**. Client sonly send inputs, which gets validated by the server.

### Move queue

If a player:

* plays too early
* plays out of turn

→ the move gets queued and processed later

This made the system way more robust.

### Selectors instead of threads

I used **event-driven I/O** instead of spawning threads per client. This scales better and avoids unnecessary complexity.

---

## ⚠️ Limitations

* CLI only (no GUI)
* No reconnection support
* No persistent game history
* Basic validation only

---

## 🔮 Future Improvements

* Web frontend or GUI
* Ranking / matchmaking system
* Reconnect support
* Better spectator experience
* Game history + analytics

---

## 🧑‍💻 Final Thoughts

This project pushed me way beyond just writing code. It forced me to think about:

* system design
* concurrency
* edge cases
* real-world failure scenarios



