import socket
import sys
import json
import threading
import time

from RtpPacket import RtpPacket
from message import MensagemControlo, MensagemFlood


class OverlayNode:
    def __init__(self, node_ip, node_id, node_type, rtsp_port, rtp_port, control_port, bootstrapper_host, bootstrapper_port):
        self.node_ip = node_ip                                                  # ip do node
        self.node_id = node_id                                                  # id do node
        self.node_type = node_type                                              # tipo do node: node/pop
        self.porta_controlo = control_port                                      # porta de controlo

        self.vizinhos = {}                                                      # dict para armazenar vizinhos ativos
        self.bootstrapper_ip = bootstrapper_host                                # ip bootstrapper
        self.bootstrapper_porta = bootstrapper_port                             # porta bootstrapper
        
        # socket rtsp - TCP
        self.porta_rtsp = rtsp_port                                             # tratar das conexoes de video
        self.rtsp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.rtsp_socket.bind((self.node_ip, self.porta_rtsp))
        self.rtsp_socket.listen(3)
        
        # socket rtp - UDP
        self.porta_rtp = rtp_port                                               # transmitir video
        self.rtp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rtp_socket.bind((self.node_ip, self.porta_rtp))
        
        self.vizinhos_streaming = {}                                            # armzenar informacoes dos vizinhos sobre streaming
        self.tabela_route = {}                                                  # info sobre as rotas
        self.streams = {}                                                       # sessoes de streams ativas

        self.lock = threading.Lock()                                            # por causa do multi-threading

    
    def start(self):
        self.bootstrapperRegister()
        threading.Thread(target=self.controlPart).start()  
        threading.Thread(target=self.pinging).start()  
        threading.Thread(target=self.vizinhoConnection).start()


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
        
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as use_socket:
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
                
                print(f"OverlayNode {self.node_id} registado com sucesso!") # debug

                # Limpa a lista de vizinhos 
                self.vizinhos.clear()  # casos de reativacao

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
                print(f"OverlayNode: {self.node_id} | Vizinhos: {self.vizinhos}")

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

            except Exception as e:
                print(f"Erro: {e}") # debug


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
                connection, _ = use_socket.accept() # aceita conexao
                
                # cria thread para tratar
                threading.Thread(target=self.controlConnHandler, args=(connection,)).start()


    def controlConnHandler(self, connection):
        """
        trata conexões de controle de outros nodes
        """
        #print(f"Conexao de controlo estabelecida") # debug
        
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
                        if mensagem_flood.type == MensagemFlood.MessageType.FLOODING_UPDATE:
                            print("MensagemFlood recebida") # debug
                            self.floodMessageHandler(mensagem_flood)
                        
                        elif mensagem_flood.type == MensagemFlood.MessageType.ATIVAR_ROTA:
                            print("MensagemFlood recebida") # debug
                            self.ativaRota(mensagem_flood)  
                                
                        else:
                            print(f"Tipo desconhecido de MensagemFlood: {mensagem_flood.type}")
                    
                    except Exception as erro:
                        print(f"Failed to parse as MensagemFlood: {erro}")
                        continue  # continua o loop e ignora a mensagem


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
                
            print(f"Node {self.node_id} | Vizinhos: {self.vizinhos}") # debug


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
                data = use_socket.recv(1024)
                if data:
                    # cria mensagem de controlo (PING_RESPONSE)
                    response_message = MensagemControlo.ParseString_control(data)
                    
                    if response_message.type == MensagemControlo.MessageType.PING_RESPONSE:
                        print(f"PING_RESPONSE de: {response_message.node_id}")
                        
                        # failed attempts resetado e status ativo
                        with self.lock: 
                            info_vizinho["ping_falhados"] = 0
                            info_vizinho["status"] = "ativo"

        except Exception as e:
            print(f"Ping falhado para o node: {info_vizinho['node_id']}: {e}")

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
    def floodMessageHandler(self, mensagem_flood):
        """
        recebe e reencaminha mensagens de flooding na rede
        """
        print(f"Flood recebido vindo do: {mensagem_flood.source_ip}") # debug

        # atualiza a tabela de rotas
        self.updateTabelaRotas(mensagem_flood)

        # cria mensagem de flood para retransmitir
        mensagem_flood.source_ip = self.node_ip
        mensagem_flood.source_id = self.node_id
        mensagem_flood.control_port = self.porta_controlo
        mensagem_flood.rtsp_port = self.porta_rtsp
        mensagem_flood.metrica += 1 # numero de saltos incrementado
        
        # vai a todos os vizinhos
        for ip_vizinho, info_vizinho in self.vizinhos.items():
            # nao reenvia para quem enviou a mensagem e garante que o node ainda não esta na route_table
            # para alem de desnecessário, evita loops infinitos de mensagens de flood
            if ip_vizinho != mensagem_flood.source_ip and ip_vizinho not in self.tabela_route :  
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as use_socket: # TCP
                        
                        use_socket.connect((ip_vizinho, info_vizinho['control_port']))
                        
                        use_socket.send(mensagem_flood.Serialize().encode('utf-8'))

                        print(f"Mensagem de Flood reencaminhada para: {info_vizinho['node_id']} | Numero de Saltos: {mensagem_flood.metrica}") # debug
                
                except Exception as erro:
                    print(f"Erro ao reencaminhar mensagem de Flood para: {info_vizinho['node_id']} - {erro}")


    def updateTabelaRotas(self, mensagem_flood):
        """
        atualiza a tabela de rotas com base na mensagem de flooding recebida
        """
        source_ip = mensagem_flood.source_ip    # node de origem da mensagem
        jumps = mensagem_flood.metrica          # metrica da mensagem de flood, numero de saltos no caso

        # itera sobre todos os fluxos de vídeo (id_filmes) recebidos
        for stream_id in mensagem_flood.id_filmes:
            # garante que a atualização da tabela de rotas seja segura
            with self.lock:
                # se source_ip ainda não estiver na tabela de rotas, cria uma entrada
                if source_ip not in self.tabela_route:
                    self.tabela_route[source_ip] = {}
                
                # se a rota para o destino e o fluxo não existirem ou se a métrica for melhor 
                if (stream_id not in self.tabela_route[source_ip] or jumps < self.tabela_route[source_ip][stream_id]['metrica']):
                    # atualiza ou adiciona a entrada de rota para esse fluxo específico
                    self.tabela_route[source_ip][stream_id] = {
                        "source_ip": mensagem_flood.source_ip,
                        "source_id": mensagem_flood.source_id,
                        "control_port": mensagem_flood.control_port,
                        "rtsp_port": mensagem_flood.rtsp_port,
                        "status": mensagem_flood.estado_rota,
                        "flow": "inativo",
                        "metrica": jumps
                    }
                            
        self.printTabelaRotas()

    
    def printTabelaRotas(self):
        """
        Imprime a tabela de rotas em um formato de tabela estruturada.
        """
        if not self.tabela_route:
            print("Tabela de rotas vazia.")
            return

        print("\n" + "=" * 80)
        print(f"{'Source IP':<15} | {'Stream ID':<10} | {'Source ID':<10} | {'Ctrl Port':<10} | {'RTSP Port':<10} | {'Status':<10} | {'Métrica':<7}")
        print("=" * 80)

        # Itera pela tabela de rotas e imprime os detalhes de cada rota
        for source_ip, streams in self.tabela_route.items():
            for stream_id, route_info in streams.items():
                print(
                    f"{source_ip:<15} | {stream_id:<10} | {route_info['source_id']:<10} | "
                    f"{route_info['control_port']:<10} | {route_info['rtsp_port']:<10} | "
                    f"{route_info['status']:<10} | {route_info['metrica']:<7}"
                )
        print("=" * 80 + "\n")
 
                    
    def ativaRota(self, mensagem_flood):
        """
        Ativa a melhor rota disponível na tabela de rotas com base na metrica
        """
        # obtem a melhor rota da tabela de rotas
        melhor_rota, filme, next_ip = self.melhorRota(mensagem_flood)
        
        # se uma melhor rota foi encontrada, marca-a como "ativa" e atualiza as sessoes
        if melhor_rota:
            with self.lock:
                # marca a rota encontrada como ativa
                self.tabela_route[next_ip][filme]['status'] = "ativo"
                
                # se o fluxo ainda não estiver registado nas sessoes, inicializa o registo
                if filme not in self.streams:
                    self.streams[filme] = {} 
                
                if mensagem_flood.source_ip not in self.streams[filme]:
                    self.streams[filme][mensagem_flood.source_ip] = {}

                # adiciona o novo receptor do vídeo à sessao
                self.streams[filme][mensagem_flood.source_ip]['rtp_port'] = mensagem_flood.rtp_port
                #print(self.streams) # debug

                # se a porta RTSP estiver disponivel, ela é adicionada à sessao
                if mensagem_flood.rtsp_port:
                    self.streams[filme][mensagem_flood.source_ip]['rtsp_port'] = mensagem_flood.rtsp_port
                
                # regista a sessao do fluxo de video
                self.streams[filme][mensagem_flood.source_ip]['session'] = filme

            print(f"Rota ativada: {melhor_rota['source_id']} até {next_ip}.") # debug
            
            self.printTabelaRotas()

            # Envia uma mensagem de ativação 
            try:
                # cria uma nova mensagem de ativação 
                mensagem_flood = MensagemFlood() 
                mensagem_flood.type = MensagemFlood.MessageType.ATIVAR_ROTA
                mensagem_flood.id_filmes.append(filme)
                mensagem_flood.source_ip = self.node_ip
                mensagem_flood.rtp_port = self.porta_rtp
                mensagem_flood.rtsp_port = self.porta_rtsp
                # nao necessita dos restantes parametros

                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as use_socket:   # TCP
                    use_socket.connect((next_ip, melhor_rota['control_port']))
                    
                    use_socket.send(mensagem_flood.Serialize().encode('utf-8'))
                    
                    print(f"Mensagem de ativação enviada para: {melhor_rota['source_id']} para o filme {filme}.") # debug
                    return
                
            except Exception as erro:
                print(f"Erro ao ativar rota para o destino {melhor_rota['source_id']} - {erro}") # debug
                return None
        
        else:
            print("Não há rotas disponiveis.") # debug
            return None
        

    def melhorRota(self, mensagem_flood):
        """
        Encontra a melhor rota disponível na tabela de rotas com base na métrica.
        """
        
        melhor_rota = None
        next_ip = None  
        filme = None

        min_metric = float('inf')  # para comparação inicial

        # Acessa os fluxos de vídeo da mensagem de flooding
        streams = mensagem_flood.id_filmes

        # Procura a melhor rota na tabela de roteamento com base no número de saltos
        with self.lock:
            # Itera sobre as rotas na tabela de roteamento
            for dest, route_info in self.tabela_route.items():
                # Para cada fluxo de vídeo recebido na mensagem, verifica se existe uma rota ativa
                for stream_id in streams:
                    
                    if stream_id in route_info:
                        
                        # Caso a rota não esteja ativa, tenta encontrar a melhor rota com a menor métrica
                        if route_info[stream_id]['metrica'] < min_metric:
                            min_metric = route_info[stream_id]['metrica']
                            melhor_rota = route_info[stream_id]
                            filme = stream_id
                            next_ip = dest

        return melhor_rota, filme, next_ip


    def vizinhoConnection(self):
        """
        Recebe pedidos de vizinhos
        """
        while True:
            try:
                # Aguarda uma conexão do vizinho (bloqueante até receber uma)
                vizinho_socket, vizinho_address = self.rtsp_socket.accept()

                # Exibe uma mensagem de debug indicando que uma conexão foi recebida
                print(f"Conexão recebida de {vizinho_address}")  # debug

                # Cria e inicia uma nova thread para lidar com o vizinho
                # A função `vizinhoHandler` será responsável por tratar a comunicação
                threading.Thread(target=self.vizinhoHandler, args=(vizinho_socket, vizinho_address)).start()
            
            except Exception as erro:
                # Em caso de erro ao aceitar uma conexão, imprime o erro de debug
                print(f"Erro ao aceitar conexão: {erro}")  # debug
                continue
    

    def vizinhoHandler(self, vizinho_socket, vizinho_address):
        """
        Função principal para lidar com as mensagens do vizinho
        """
        filme = None

        while True:
            try:
                # recebe pedido do vizinho
                request = vizinho_socket.recv(1024).decode()

                if not request:
                    break
                
                else:
                    print(f"Pedido recebido do vizinho: {vizinho_address}:\n{request}") # debug

                    # divide a requisição em linhas e extrai o nome do arquivo (fluxo de vídeo) e o IP do cliente.
                    lines = request.splitlines()
                    lines_splited = lines[0].split(' ')
                    filme = lines_splited[1]
                    
                    dest_ip = self.getRequestIP(request)
                    
                    # inicializa o dicionário de sessoes, se ainda nao existir
                    with self.lock:
                        if filme not in self.streams:
                            self.streams[filme] = {}
                        if dest_ip not in self.streams[filme]:
                            self.streams[filme][dest_ip] = {}
                    
                    # Define o status inicial da rota como "INIT" se não estiver definido.
                    with self.lock:
                        if 'status' not in self.streams[filme][dest_ip]: 
                            self.streams[filme][dest_ip]['status'] = "INIT"
                    
                    # obtem o status da conexao 
                    status_vizinho = self.streams[filme][dest_ip]['status']
                    
                    # obtem a rota pro fluxo de video
                    rota = self.getRotaFilme(filme) 
                    
                    # INIT e SETUP 
                    if status_vizinho == "INIT" and "SETUP" in request: 
                        # caso o node ja esteja a receber dados
                        if rota: 
                            print("ROTA JA EXISTIA!!!")
                            seq_number = lines[1].split(' ')[1]                # obtem o número da sequencia da requisicao
                            self.replyRtsp(seq_number, filme, vizinho_socket) 

                        # senao redireciona a requisicao para o proximo node  
                        else: 
                            # substitui o IP do cliente pela IP do node
                            request_alterado = self.trocaIP(request, self.node_ip)
                            destino, _ = self.forward_request(filme, request_alterado, vizinho_socket)
                            
                            # marca a rota como ativa na tabela de rotas
                            with self.lock: 
                                self.tabela_route[destino][filme]['flow'] = "ativo"
                        
                        # atualiza o status do vizinho apos o SETUP
                        with self.lock: 
                            self.streams[filme][dest_ip]['status'] = "READY"
                        
                    # READY e PLAY    
                    elif status_vizinho == "READY" and "PLAY" in request:  
                        # se ja houver fluxo de dados para o node
                        if rota and self.someoneUsingQM(filme): 
                            seq_number = lines[1].split()[1]                    # obtem o número da sequencia da requisicao
                            self.replyRtsp(seq_number, filme, vizinho_socket) 
                        
                        # senao, reencaminha a requisicao
                        else:  
                            request_alterado = self.trocaIP(request, self.node_ip)
                            _, _  = self.forward_request(filme, request_alterado, vizinho_socket)
                        
                        # marca o fluxo como "YES" e atualiza o status do vizinho pra "PLAYING"
                        with self.lock: 
                            self.streams[filme][dest_ip]['flow'] = "ativo"
                            self.streams[filme][dest_ip]['status'] = "PLAYING"
                        
                        # inicia uma nova thread para encaminhar pacotes RTP para um vizinho específico 
                        threading.Thread(target=self.forward_rtp).start()
                    
                    # PLAYING e PAUSE 
                    elif status_vizinho == "PLAYING" and "PAUSE" in request:    
                        # se ha multiplos vizinhos a receber dados         
                        if self.variousUsingQM(filme):
                            seq_number = lines[1].split(' ')[1]                        # obtem o número da sequencia da requisicao
                            self.replyRtsp(seq_number, filme, vizinho_socket) 

                        # senao, reencaminha a requisicao                     
                        else: 
                            request_alterado = self.trocaIP(request, self.node_ip)
                            self.forward_request(filme, request_alterado, vizinho_socket)
                        
                        # marca o fluxo como "NO" e atualiza o status do vizinho pra "READY"
                        with self.lock: 
                            self.streams[filme][dest_ip]['flow'] = "inativo"
                            self.streams[filme][dest_ip]['status'] = "READY"
                    
                    # TEARDOWN
                    elif "TEARDOWN" in request:   
                        self.removeConexao(filme, dest_ip, request, vizinho_socket) # remove a conexao do vizinho
                    
            except Exception as erro:
                print(f"Ocorreu um erro - {erro}")
                break
    

    def getRotaFilme(self, stream_id):
        """
        Verifica se existe uma rota ativa para um filme especificado na tabela de roteamento
        Retorna as informações da rota se encontrada, caso contrário, retorna None
        """
        with self.lock:
            # itera pela tabela de roteamento
            for destino, rota in self.tabela_route.items():
                # verifica se a stream_id está presente nas rotas e se o fluxo está ativo ('flow' == "activa")
                if stream_id in rota and rota[stream_id].get('flow') == "ativo":
                    print("JA EXISTE ROTA!!!!")
                    # retorna um dicionário contendo o destino e as informações da rota ativa
                    return {
                        "destination": destino,
                        "route_info": rota[stream_id]
                    }
                
        return None
    

    def getRotaAtiva(self, stream_id):
        """
        Verifica se existe uma rota ativa para um filme especificado na tabela de roteamento
        Retorna as informações da rota se encontrada, caso contrário, retorna None
        """
        with self.lock:
            # itera pela tabela de roteamento
            for destino, rota in self.tabela_route.items():
                # verifica se o stream_id está presente nas rotas e se o status é "active"
                if stream_id in rota and rota[stream_id].get("status") == "ativo":
                    # retorna um dicionário contendo o destino e as informações da rota ativa
                    return {
                        "destination": destino,
                        "route_info": rota[stream_id]
                    }
        
        return None
    

    def replyRtsp(self, seq_number, stream, vizinho_socket):
        """
        Envia uma resposta RTSP ao cliente
        """
        resposta = 'RTSP/1.0 200 OK\nCSeq: ' + seq_number + '\nSession: ' + stream
        vizinho_socket.send(resposta.encode())


    def getRequestIP(self, pedido):
        """
        Extrai o IpCliente de uma requisição RTSP
        """
        # divide o pedido em linhas individuais
        linhas = pedido.splitlines()

        # itera sobre cada linha do pedido
        for linha in linhas:
            # se encontrar "IpCliente", divide a linha pelo char ":" e retorna o segundo valor (ip)
            if "IpCliente" in linha:
                #print(line.split(": ")[1]) # debug
                return linha.split(": ")[1]
        
        return None
    
    def trocaIP(self, pedido, new_ip):
        """
        Substitui o IpCliente na requisição por um novo IP
        """
        ret = [] # request que vai ser retornado

        # divide o pedido em linhas individuais
        linhas = pedido.splitlines()

        # itera sobre cada linha do pedido
        for linha in linhas:
            # se a linha tem o cabeçalho "IpCliente", substitui o IP antigo pelo novo
            if "IpCliente" in linha:
                ret.append(f"IpCliente: {new_ip}")

            # senao apenas coloca a linha normalmente
            else:
                ret.append(linha)
        
        # recria o pedido, alterado
        return "\n".join(ret)


    def forward_request(self, filme, request, vizinho_socket):
        """
        Encaminha a requisição RTSP recebida de um vizinho para o próximo nó ativo na rota de transmissão do vídeo
        """
        # obtem a rota ativa para o fluxo do filme
        rota_ativa = self.getRotaAtiva(filme)

        # extrai a porta RTSP do vizinho ativo que fará a conexao para o fluxo de video
        porta_rtsp = rota_ativa['route_info']['rtsp_port']

        # obtem o destino da rota ativa, ou seja, o IP do próximo nó na rota de transmissão.
        next_ip = rota_ativa['destination']

        # cria ou obtem uma conexão RTSP com o vizinho ativo
        rtsp_socket = self.getSocketRTSP(next_ip, porta_rtsp) 

        # reencaminha lhe o pedido 
        self.sendRequestRTSP(rtsp_socket, request, vizinho_socket) 

        # retorna o IP do proximo node e a porta RTSP usada para a conexao 
        return next_ip, porta_rtsp
    
    
    def someoneUsingQM(self, filme):
        """
        Verifica se existe pelo menos uma sessão ativa para o filme especificado
        Retorna True se existir pelo menos uma sessão ativa, caso contrário, retorna False
        """
        with self.lock:
            # Retorna True assim que encontrar uma sessão com 'flow' ativo
            return any(session_info.get('flow') == "ativo" for session_info in self.streams.get(filme, {}).values())
    
    
    def variousUsingQM(self, filme):
        """
        Verifica se há mais de uma sessão ativa para o filme especificado
        Retorna True se houver mais de uma sessão ativa, caso contrário, retorna False
        """
        with self.lock:
            # Conta o número de sessões com 'flow' ativo e retorna True se for maior que 1
            return sum(1 for session_info in self.streams.get(filme, {}).values() if session_info.get('flow') == "ativo") > 1
            

    def getSocketRTSP(self, destination_ip, rtsp_port):
        """
        Verifica se uma conexão RTSP persistente já existe para o IP e porta de destino
        Caso não exista, cria uma nova conexão e a armazena. Retorna o socket RTSP
        """
        # inicializa a estrutura para armazenar conexoes RTSP para o destino, se nao existir
        if destination_ip not in self.vizinhos_streaming:
            self.vizinhos_streaming[destination_ip] = {}

        if 'rtsp_socket' in self.vizinhos_streaming[destination_ip]:
            print(f"Conexão RTSP já existente para {destination_ip}:{rtsp_port}")
            return self.vizinhos_streaming[destination_ip]['rtsp_socket']
        
        # verifica se ja existe um socket RTSP associado ao destino 
        else:  
            try:
                # cria um novo socket RTSP
                rtsp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # TCP
                rtsp_socket.connect((destination_ip, rtsp_port)) # Conecta ao destino usando IP e porta RTSP

                # armazena o socket RTSP no dicionário 
                with self.lock:
                    self.vizinhos_streaming[destination_ip]['rtsp_socket'] = rtsp_socket

                print(f"Conexão RTSP criada para {destination_ip}:{rtsp_port}") # debug
                
            except Exception as erro:
                print(f"Erro ao criar conexão RTSP - {erro}")
                return None
            
            # retorna o socket RTSP definido
            return self.vizinhos_streaming[destination_ip]['rtsp_socket']


    def sendRequestRTSP(self, rtsp_socket, request, vizinho_socket):
        """
        Envia uma requisição RTSP a um destino e encaminha a resposta de volta ao vizinho solicitante
        """
        try:
            # Envia a requisição RTSP para o destino atraves do socket RTSP fornecido
            rtsp_socket.send(request.encode())
            print(f"Request RTSP enviado") # debug

            # Recebe a resposta do destino RTSP
            resposta = rtsp_socket.recv(1024).decode()

            # Enviar a resposta de volta ao vizinho
            vizinho_socket.send(resposta.encode())
            print(f"Reencaminhou a resposta recebida") # debug
                
        except Exception as erro:
            print(f"Falha ao enviar requisição RTSP - {erro}")


    def forward_rtp(self):
        """
        Responsável por encaminhar pacotes RTP (Real-Time Protocol) recebidos para os clientes conectados
        """
        print("Encaminhamento de pacotes RTP iniciado.")  # Debug                  
        
        while True:
            # Recebe um pacote RTP no socket
            data, _ = self.rtp_socket.recvfrom(20480)
            
            if data:
                # decodifica o pacote RTP 
                rtp_packet = RtpPacket()
                stream_id = rtp_packet.decode(data) # extrai o nome do video do pacote recebido 
                
                with self.lock: 
                    # itera pelos clientes associados ao fluxo atual
                    for vizinho_ip, vizinho_info in self.streams[stream_id].items():
                        
                        vizinho_socket = None
                        vizinho_rtp_port = None
                        
                        # verifica e cria um socket RTP para o vizinhoe, se ainda nao existir
                        if "rtpSocket" not in vizinho_info:
                            vizinho_info["rtpSocket"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

                        vizinho_socket = vizinho_info["rtpSocket"]

                        if "rtp_port" in vizinho_info:
                            vizinho_rtp_port = vizinho_info['rtp_port']
                        #vizinho_rtp_port = vizinho_info['rtp_port']
                        #print("PORTA ERRO:")
                        #print(vizinho_info['rtp_port'])

                        # verifica se o fluxo esta ativo para este vizinho
                        if "flow" in vizinho_info and vizinho_info["flow"] == "ativo" and vizinho_socket and vizinho_rtp_port:
                            # Encaminha o pacote RTP para o vizinhoe
                            vizinho_socket.sendto(data, (vizinho_ip, vizinho_rtp_port)) # UDP
                            
                            print(f"Pacote RTP recebido. A reencaminhar para: {vizinho_ip}:{vizinho_rtp_port}") # debug
            
             
    def removeConexao(self, filme, vizinho_address, request, vizinho_socket):
        """
        Remove uma conexão com um cliente vizinho, notificando-o para parar o envio de pacotes RTP 
        e limpa os recursos associados à sessão
        """
        # obtem a rota ativa associada ao fluxo (filme)
        rota_ativa = self.getRotaAtiva(filme)

        if rota_ativa is None:
            print(f"Não há rota ativa para o filme {filme}.")  # debug
            return

        # recupera as informações da rota ativa
        porta_rtsp = rota_ativa['route_info']['rtsp_port']
        destino = rota_ativa['destination']
        
        # estabelece uma conexão RTSP com o vizinho ativo
        rtsp_socket = self.getSocketRTSP(destino, porta_rtsp) # Conecta se com o vizinho ativo
        
        # reencaminha a requisição RTSP
        #self.sendRequestRTSP(rtsp_socket, request, vizinho_socket)   
        
        # aguarda um curto periodo antes de liberar os recursos
        time.sleep(3)      
                    
        with self.lock: 
            # verifica se o fluxo e o cliente existem na tabela de sessões
            if filme in self.streams and vizinho_address in self.streams[filme]:
                # fecha o socket RTP se ele existir
                if "rtpSocket" in self.streams[filme][vizinho_address]:
                    
                    try:    
                        self.streams[filme][vizinho_address]["rtpSocket"].close()
                        print(f"RTP socket para {vizinho_address} fechado.") # debug
                    
                    except Exception as erro:
                        print(f"Erro ao fechar RTP socket - {erro}") # debug
                
                # Remove o cliente do dicionario
                self.streams[filme].pop(vizinho_address)
                print(f"Cliente {vizinho_address} removido de {filme}") # debug

                # Se não houver mais clientes associados ao fluxo, remove o fluxo da tabela de sessões
                if not self.streams[filme]:  
                    # reencaminha a requisição RTSP
                    self.sendRequestRTSP(rtsp_socket, request, vizinho_socket)
                    self.streams.pop(filme)    
                    print(f"Removido {filme} das streams.") # debug
            
            else:
                print(f"Cliente {vizinho_address} não encontrado para a stream: {filme}") # debug

   
"""
main
"""
if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python3 OverlayNode.py <nodeX>.json")
        sys.exit(1)

    config_file = sys.argv[1]
    
    try:
        with open(config_file, 'r') as file:
            config = json.load(file)
    except Exception as e:
        print(f"Error reading config file: {e}")
        sys.exit(1)

    node_ip = config["node_ip"]
    node_id = config["node_id"]
    node_type = config["node_type"]
    rtsp_port = config["rtsp_port"]
    rtp_port = config["rtp_port"]
    control_port = config["control_port"]
    bootstrapper_ip = config["bootstrapper_ip"]
    bootstrapper_port = config["bootstrapper_port"]

    node = OverlayNode(
        node_ip, 
        node_id,
        node_type, 
        rtsp_port, 
        rtp_port, 
        control_port,  
        bootstrapper_ip,
        bootstrapper_port
    )

    node.start()
