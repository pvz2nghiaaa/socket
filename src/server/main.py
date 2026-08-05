import socket
import threading
import time

# Import team modules directly
from ..utils import multithreading
# from ..protocol import udp_packet


class HybridFTPServerCLI:
    def __init__(self, host='127.0.0.1', port=2121):
        self.host = host
        self.port = port
        self.server_socket = None
        self.accept_thread = None
        self.is_running = False
        self.start_time = None

    def start_server(self):
        """Initiates the TCP server socket: socket creation, bind, listen, and accept loop."""
        if self.is_running:
            print("[Server] Server is already running.")
            return

        try:
            # 1. Socket Creation (IPv4, TCP Stream)
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Re-use socket address to avoid "Address already in use" errors on immediate restarts
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # 2. Bind host and port
            self.server_socket.bind((self.host, self.port))

            # 3. Listen for incoming client connections (backlog queue = 5)
            self.server_socket.listen(5)
            self.server_socket.settimeout(1.0)  # Non-blocking check interval

            self.is_running = True
            multithreading.shutdown_event.clear()
            self.start_time = time.time()

            # 4. Start accepting connections in a background thread
            self.accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
            self.accept_thread.start()

            print(f"[Server] TCP Control channel initialized on {self.host}:{self.port}")
        except Exception as e:
            print(f"[Server Error] Could not start server: {e}")
            self.is_running = False

    def _accept_loop(self):
        """Background worker continuously running accept()."""
        while self.is_running and not multithreading.shutdown_event.is_set():
            try:
                # Accept incoming connection
                client_socket, client_addr = self.server_socket.accept()

                # Delegate thread creation to multithreading module
                multithreading.create_thread(
                    client_socket,
                    client_addr,
                    multithreading.ftp_task_function
                )
            except socket.timeout:
                continue
            except OSError:
                break  # Triggered when socket is closed on shutdown

    def display_state(self):
        """Prints current network and server execution state."""
        print("\n--- Server State ---")
        print(f"Status:       {'RUNNING' if self.is_running else 'STOPPED'}")
        print(f"Bind IP:      {self.host}")
        print(f"Control Port: {self.port} (TCP)")
        if self.is_running and self.start_time:
            uptime = int(time.time() - self.start_time)
            print(f"Uptime:       {uptime} seconds")

    def display_processes(self):
        """Prints active client threads monitored by multithreading module."""
        multithreading.close_inactive_thread()
        with multithreading.lock:
            active_threads = list(multithreading.listThread)

        print("\n--- Active Processes & Threads ---")
        print(f"Active Client Threads: {len(active_threads)}")
        for idx, thread in enumerate(active_threads, start=1):
            print(f"  [{idx}] Thread: {thread.name} | Status: {'Alive' if thread.is_alive() else 'Dead'}")

    def stop_server(self):
        """Gracefully halts the server and delegates client cleanup to team module."""
        if not self.is_running:
            print("[Server] Server is not currently active.")
            return

        self.is_running = False
        if self.server_socket:
            # Delegate thread joining and socket cleanup to imported module
            multithreading.shutdown_monitor(self.server_socket)
            self.server_socket = None

    def start_loop(self):
        """Main CLI loop for user commands."""
        print("==============================================")
        print("      Hybrid FTP Server Interactive CLI       ")
        print("==============================================")
        print("Commands: start | state | processes | stop | help | exit\n")

        # Automatically start socket initiation on launch
        self.start_server()

        while True:
            try:
                status = "RUNNING" if self.is_running else "STOPPED"
                user_input = input(f"[{status}]> ").strip()

                if not user_input:
                    continue

                cmd = user_input.split(maxsplit=1)[0].lower()

                if cmd == 'start':
                    self.start_server()
                elif cmd == 'state':
                    self.display_state()
                elif cmd == 'processes':
                    self.display_processes()
                elif cmd == 'stop':
                    self.stop_server()
                elif cmd == 'help':
                    print("\nCLI Commands:")
                    print("  start     - Execute socket bind, listen, and accept")
                    print("  state     - Show server status, IP, port, and uptime")
                    print("  processes - Show active connection threads")
                    print("  stop      - Disconnect clients and stop listening")
                    print("  exit/quit - Stop server and terminate program")
                elif cmd in ('exit', 'quit'):
                    self.stop_server()
                    print("Exiting CLI application.")
                    break
                else:
                    print(f"Unknown command: '{cmd}'. Type 'help' for options.")

            except KeyboardInterrupt:
                print("\nKeyboard interrupt detected.")
                self.stop_server()
                break

print(__name__)
if __name__ == "__main__":
    cli = HybridFTPServerCLI()
    cli.start_loop()