import socket


def send_magic_packet(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    normalized = mac.replace(":", "").replace("-", "").replace(".", "")
    if len(normalized) != 12:
        raise ValueError("Wake-on-LAN MAC address must contain 12 hexadecimal characters")
    try:
        payload = bytes.fromhex("FF" * 6 + normalized * 16)
    except ValueError as exc:
        raise ValueError("Wake-on-LAN MAC address is invalid") from exc
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(payload, (broadcast, port))
