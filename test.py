
import socket

s = socket.socket()
s.bind(('192.168.1.241', 502))
s.listen(1)
conn, addr = s.accept()
conn.settimeout(0.0001)


while True:
    data = conn.recv(1024)
    print(f'Сервер получил {data}')

    send_mes = str.encode(str(1) + '\r\n') 
    conn.send(send_mes)


SocketTest = SocketClass("192.168.1.90", 502, ",", "\r\n", nil, 0.01, 1)
SocketTest:Send('ready')

while true do 
    rets = SocketTest:Receive()
    num = tonumber(rets[1])
    print(num)
    SocketTest:Send(num)
end