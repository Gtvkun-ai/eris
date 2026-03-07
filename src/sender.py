import socket # Socket dùng để tạo kết nối TCP/IP
import time # Thư viện time để sử dụng hàm sleep

# Cấu hình địa chỉ và cổng
UDP_IP = "127.0.0.1"  # Localhost (chính máy của Ngài)
UDP_PORT = 4242
MESSAGE = "Hello World"

# Khởi tạo Socket UDP
# AF_INET: Sử dụng IPv4
# SOCK_DGRAM: Giao thức UDP
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

print(f"Đang gửi tin nhắn đến {UDP_IP}:{UDP_PORT}...")

try:
    while True:
        #Gửi tin nhắn (Phải encode sang bytes trước khi gửi)
        sock.sendto(MESSAGE.encode('utf-8'), (UDP_IP, UDP_PORT))
        print(f"Đã gửi: {MESSAGE}")
        time.sleep(1)  # Đợi 1 giây trước khi gửi tin nhắn tiếp theo

except KeyboardInterrupt:
    print("Đã dừng gửi tin nhắn.")
finally:
    sock.close()  # Đóng socket khi hoàn thành