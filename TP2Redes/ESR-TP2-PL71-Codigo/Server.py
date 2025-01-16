import sys
import json
import socket
import threading
import time

from ServerWorker import ServerWorker
from message import MensagemControlo, MensagemFlood

class Server:
    def __init__(self,server_ip, server_id, control_port, server_rtsp_port, bootstrapper_host, bootstrapper_port):
        self.node_id = server_id                                            # id do server
        self.node_ip = server_ip                                            # ip do server
        self.node_type = "server"                                           # tipo do node
        self.porta_controlo = control_port                                  # porta de controlo

        self.vizinhos = {}                                                  # dict para armazenar vizinhos ativos
        self.bootstrapper_ip = bootstrapper_host                            # ip bootstrapper
        self.bootstrapper_porta = bootstrapper_port                         # porta bootstrapper

        self.vizinhos_streaming = {}                                        # armzenar informacoes dos vizinhos sobre streaming
        self.porta_rtsp = server_rtsp_port                                  # porta rtsp do servidor - pedidos streaming
        self.socket_rtsp = None                                             # pedidos streaming

        #self.filmes = {"movie.Mjpeg", "filme.Mjpeg"}                        # filmes disponiveis
        self.filmes = {"video.mjpeg", "filme.mjpeg"}                        # filmes disponiveis
        
        self.lock = threading.Lock()                                        # por causa do multi-threading


    def start(self):
        self.bootstrapperRegister()
        threading.Thread(target=self.controlPart).start()
        threading.Thread(target=self.pinging).start()
        threading.Thread(target=self.initFlood).start()

    """
    @@@@@ bootstrapper
    """
    def bootstrapperRegister(self):
        """
        regista o node no Bootstrapper e recebe a lista de vizinhos
        """
        # cria mensagem de controlo para registar o node
        mensagem_controlo = MensagemControlo()
        mensagem_controlo.type = MensagemControlo.MessageType.REGISTER
        mensagem_controlo.node_id = self.node_id
        mensagem_controlo.node_ip = self.node_ip
        mensagem_controlo.node_type = self.node_type
        mensagem_controlo.control_port = self.porta_controlo

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as use_socket:   # TCP
            # conecta ao bootstraper
            use_socket.connect((self.bootstrapper_ip, self.bootstrapper_porta))

            # envia a mensagem ao bootstrapper
            use_socket.send(mensagem_controlo.Serialize().encode('utf-8'))

            # recebe a resposta do boostrapper
            response = use_socket.recv(1024)

            if not response:
                print("Nenhuma resposta recebida do Bootstrapper.")
                return

            # intrepreta a mensagem recebida
            response_message = MensagemControlo.ParseString_control(response)

            # verifica se a resposta.type == "REGISTER_RESPONSE"
            if response_message.type == MensagemControlo.MessageType.REGISTER_RESPONSE:

                print(f"Servidor {self.node_id} registado com sucesso!") # debug

                # Limpa a lista de vizinhos
                self.vizinhos.clear() # casos de reativacao

                # atualiza a lista de vizinhos com a resposta recebida
                for vizinho in response_message.neighbors:
                    with self.lock: # usa o lock para garantir acesso seguro ao dicionário de vizinhos
                        self.vizinhos[vizinho.node_ip] = {
                            "node_id": vizinho.node_id,
                            "control_port": vizinho.control_port,
                            "node_type": vizinho.node_type,
                            "status": "ativo",
                            "ping_falhados": 0
                        }

                # imprime a lista de vizinhos atualizada
                print(f"Servidor: {self.node_id} | Vizinhos: {self.vizinhos}")

                # notifica os vizinhos sobre o registo
                self.registrationNotify()

            else:
                print(f"Resposta recebida com o tipo Errado") # debug


    def registrationNotify(self):
        """
        notifica os vizinhos que um node foi registado
        """
        # cria uma mensagem de controlo para enviar aos vizinhos
        mensagem_controlo = MensagemControlo()
        mensagem_controlo.type = MensagemControlo.MessageType.VIZINHOS_UPDATE
        mensagem_controlo.node_id = self.node_id
        mensagem_controlo.node_ip = self.node_ip
        mensagem_controlo.node_type = self.node_type
        mensagem_controlo.control_port = self.porta_controlo

        # percorre todos os vizinhos do dicionario
        for ip_vizinho, info_vizinho in self.vizinhos.items():
            try:
                # cria um socket para se conectar ao vizinho
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as use_socket: # TCP
                    # conecta ao vizinho
                    use_socket.connect((ip_vizinho, info_vizinho['control_port']))

                    # envia a mensagem criada
                    use_socket.send(mensagem_controlo.Serialize().encode('utf-8'))

                    print(f"Vizinho {info_vizinho['node_id']} notificado") # debug

            except Exception as erro:
                print(f"Erro - {erro}") # debug

    """
    @@@@@ controlo
    """
    def controlPart(self):
        """
        thread para conexões de outros nodes para pings e atualizações de vizinhos
        """
        # cria um socket para o "servidor de controlo"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as use_socket: # TCP

            use_socket.bind(('', self.porta_controlo))    # ip local e porta especificada

            use_socket.listen() # aguarda conexões

            # loop infinito para aceitar conexoes de controlo
            while True:
                connection, address = use_socket.accept() # aceita conexao

                # cria thread para tratar
                threading.Thread(target=self.controlConnHandler, args=(connection, address)).start()


    def controlConnHandler(self, connection, address):
        """
        trata conexões de controlo de outros nodes
        """
        print(f"Conexao de controlo estabelecida com {address}") # debug

        with connection:
            while True:
                data = connection.recv(1024)

                if not data:
                    break

                try:
                    mensagem_controlo = MensagemControlo.ParseString_control(data)

                    # Se o tipo da mensagem for de atualização de vizinhos
                    if mensagem_controlo.type == MensagemControlo.MessageType.VIZINHOS_UPDATE:
                        self.vizinhosUpdateHandler(mensagem_controlo)

                    # Se o tipo da mensagem for um PING
                    elif mensagem_controlo.type == MensagemControlo.MessageType.PING:
                        self.pingHandler(mensagem_controlo, connection)

                    else:
                        raise ValueError(f"Tipo de MensagemControlo desconhecido: {mensagem_controlo.type}")

                except Exception as e:
                    #print(f"Mensagem recebida não é de Controlo, vamos ver se é de Flood") # debug

                    # Se nao for MensagemControlo tenta ver se é MensagemFlood
                    try:
                        mensagem_flood = MensagemFlood.ParseString_flood(data)

                        # Se o tipo da mensagem for MensagemFlood
                        if mensagem_flood.type == MensagemFlood.MessageType.ATIVAR_ROTA:
                            print("MensagemFlood recebida") # debug
                            self.vizinhosStreamingInfo(mensagem_flood)

                        else:
                            print(f"Tipo desconhecido de MensagemFlood: {mensagem_flood.type}")

                    except Exception as erro:
                        print(f"Failed to parse as MensagemFlood: {erro}")
                        continue    # continua o loop e ignora a mensagem


    def vizinhosUpdateHandler(self, mensagem_controlo):
        """
        atualiza a lista de vizinhos do node com a mensagem de controle recebida
        """
        print("A atualizar vizinhos..") # debug

        id_vizinho = mensagem_controlo.node_id
        ip_vizinho = mensagem_controlo.node_ip
        tipo_node = mensagem_controlo.node_type
        porta_controlo = mensagem_controlo.control_port

        with self.lock: # garante acesso ao dicionário de vizinhos seguro

            # se o vizinho não tiver na lista de vizinhos então cria
            if ip_vizinho not in self.vizinhos:
                self.vizinhos[ip_vizinho] = {
                    "node_id": id_vizinho,
                    "node_type": tipo_node,
                    "control_port": porta_controlo,
                    "ping_falhados": 0,
                    "status": "ativo"
                }

            # senão apenas coloca como ativo
            else:
                self.vizinhos[ip_vizinho]["status"] = "ativo"

            print(f"Servidor {self.node_id} | Vizinhos: {self.vizinhos}") # debug

    def pinging(self):
        """
        Envia um PING pros vizinhos a cada 20 segundos e monitora as suas respostas
        """
        while True:
            # itera sob todos os vizinhos
            for ip_vizinho, info_vizinho in list(self.vizinhos.items()):
                # se o estado do vizinho for inativo então ignora
                if info_vizinho.get("status") == "inativo":
                    continue

                # se o houver mais de 3 falhas ao contactar o vizinho
                if info_vizinho.get("ping_falhados", 0) >= 3:
                    # então torna esse vizinho inativo
                    with self.lock:
                        info_vizinho["status"] = "inativo"

                    print(f"Vizinho {info_vizinho['node_id']} tornado inativo") # debug
                    continue

                self.ping_vizinho(ip_vizinho, info_vizinho)

            # Aguarda 20 segundos entre os pings
            time.sleep(20)


    def ping_vizinho(self, ip_vizinho, info_vizinho):
        """
        tenta enviar um PING para um vizinho e processa a resposta
        """
        try:
            # cria uma socket para enviar o pings
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as use_socket: # TCP
                use_socket.connect((ip_vizinho, info_vizinho['control_port']))

                # cria uma mensagem de controlo (ping)
                mensagem_controlo = MensagemControlo()
                mensagem_controlo.type = MensagemControlo.MessageType.PING
                mensagem_controlo.node_ip = self.node_ip
                mensagem_controlo.node_id = self.node_id
                mensagem_controlo.node_type = self.node_type
                mensagem_controlo.control_port = self.porta_controlo

                use_socket.send(mensagem_controlo.Serialize().encode('utf-8'))

                print(f"PING enviado para: {info_vizinho['node_id']}") # debug

                # espera pela resposta (PING_RESPONSE)
                response = use_socket.recv(1024)
                if response:
                    # cria mensagem de controlo (PING_RESPONSE)
                    response_message = MensagemControlo.ParseString_control(response)

                    if response_message.type == MensagemControlo.MessageType.PING_RESPONSE:
                        print(f"PING_RESPONSE de: {response_message.node_id}")

                        # failed attempts resetado e status ativo
                        with self.lock:
                            info_vizinho["ping_falhados"] = 0
                            info_vizinho["status"] = "ativo"

        except Exception as erro:
            print(f"Ping falhado para o node:{info_vizinho['node_id']} - {erro}")

            # Incrementa o nr de ping_falhados caso erro
            with self.lock:
                info_vizinho["ping_falhados"] = info_vizinho.get("ping_falhados", 0) + 1


    def pingHandler(self, mensagem_controlo, connection):
        """
        trata mensagens de ping recebidas e responde com mensagens de PING_RESPONSE
        """
        print(f"PING recebido de: {mensagem_controlo.node_id}") # debug

        # cria mensagem de controlo resposta
        mensagem_controlo = MensagemControlo()
        mensagem_controlo.type = MensagemControlo.MessageType.PING_RESPONSE
        mensagem_controlo.node_id = self.node_ip
        mensagem_controlo.node_id = self.node_id
        mensagem_controlo.node_type = self.node_type
        mensagem_controlo.control_port = self.porta_controlo

        connection.send(mensagem_controlo.Serialize().encode('utf-8'))

        print(f"PING_RESPONSE enviado para: {mensagem_controlo.node_id}") # debug

        # torna o status ativo e renicia os failed attempts para o node que enviou o ping
        with self.lock:
            if mensagem_controlo.node_ip in self.vizinhos:
                self.vizinhos[mensagem_controlo.node_ip]["status"] = "ativo"
                self.vizinhos[mensagem_controlo.node_ip]["ping_falhados"] = 0

    """
    @@@@@ flooding
    """
    def initFlood(self):
        """
        Envia uma mensagem de flood para todos os vizinhos ativos
        """
        while True: #infinitamente

            # cria uma mensagem de flood
            mensagem_flood = MensagemFlood()
            mensagem_flood.type = MensagemFlood.MessageType.FLOODING_UPDATE
            mensagem_flood.source_id = self.node_id
            mensagem_flood.source_ip = self.node_ip
            mensagem_flood.control_port = self.porta_controlo
            mensagem_flood.rtsp_port = self.porta_rtsp
            mensagem_flood.estado_rota = "inativa"
            mensagem_flood.metrica = 0
            mensagem_flood.id_filmes.extend(self.filmes)

            # envia a mensagem
            self.sendFlood(mensagem_flood)

            time.sleep(30) # 1 flood a cada X segs

    def sendFlood(self, mensagem_flood):
        """
        Envia uma mensagem de flood para todos os seus vizinhos
        """
        # vai a todos os vizinhos
        for ip_vizinho, info_vizinho in self.vizinhos.items():

            if info_vizinho.get("status") != "ativo":
                continue  # ignora vizinhos inativos

            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as use_socket:   # TCP
                    use_socket.connect((ip_vizinho, info_vizinho['control_port']))

                    use_socket.send(mensagem_flood.Serialize().encode('utf-8'))

                    print(f"Mensagem de Flood enviada para: {info_vizinho['node_id']}") # debug

            except Exception as erro:
                print(f"Erro a enviar mensagem de Flood para: {info_vizinho['node_id']} - {erro}")


    def vizinhosStreamingInfo(self, mensagem_flood):
        """
        Atualiza informações de streaming dos vizinhos e inicia o socket RTSP
        """
        # Verifica se o IP do vizinho já está registado no dicionário `vizinhos_streaming`
        # Se não estiver, inicializa com um dicionário vazio
        if mensagem_flood.source_ip not in self.vizinhos_streaming:
            self.vizinhos_streaming[mensagem_flood.source_ip] = {}

        # Verifica se a chave 'rtp_port' não está presente no registro deste vizinho
        # Caso não esteja, adiciona a porta RTP enviada na mensagem de flood
        if 'rtp_port' not in self.vizinhos_streaming[mensagem_flood.source_ip]:
            self.vizinhos_streaming[mensagem_flood.source_ip]['rtp_port'] = mensagem_flood.rtp_port

        # Cria uma nova thread para lidar com o socket RTSP do vizinho identificado pelo IP
        threading.Thread(target=self.serverRTSP, args=(mensagem_flood.source_ip,)).start()

    def serverRTSP(self, node_ip):
        """
        Cria um servidor RTSP e aguarda conexões de clientes RTSP
        """
        # se o socket ainda n foi iniciado cria um novo
        if self.socket_rtsp is None:
            self.socket_rtsp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket_rtsp.bind(('', self.porta_rtsp)) # host local
            self.socket_rtsp.listen(3)  # recebe ate 3 conexoes
            print(f"Server RTSP :{self.porta_rtsp}")

        # loop infinito para aguardar conexões de clientes RTSP
        while True:
            # cria um dicionário para armazenar informações do vizinho
            vizinhoInfo = {}

            # aguarda uma conexão de um cliente RTSP
            vizinhoInfo['rtspSocket'], _ = self.socket_rtsp.accept()

            # adiciona a porta RTP do vizinho (da lista de streaming)
            vizinhoInfo['rtp_port'] = self.vizinhos_streaming[node_ip]['rtp_port']

            # armazena o IP do vizinho
            vizinhoInfo['ip'] = node_ip

            # Inicia um ServerWorker para lidar com a conexão RTSP desse vizinho
            server_worker = ServerWorker(vizinhoInfo)  # Cria uma instância do worker.
            server_worker.run()  # Executa o trabalho de processamento da conexão.

"""
@@@@@ main
"""
if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python3 Server.py <servidor>.json>")
        sys.exit(1)

    config_file = sys.argv[1]

    try:
        with open(config_file, 'r') as file:
            config = json.load(file)
    except FileNotFoundError:
        print(f"Error: Config file '{config_file}' not found.")
        sys.exit(1)

    server_ip = config.get("server_ip")
    server_id = config.get("node_id")
    server_port = config.get("server_port")
    control_port = config.get("control_port")
    bootstrapper_ip = config.get("bootstrapper_ip")
    bootstrapper_port = config.get("bootstrapper_port")

    server = Server(
        server_ip,
        server_id,
        server_port,
        control_port,
        bootstrapper_ip,
        bootstrapper_port
    )

    server.start()



