from tkinter import *
import tkinter.messagebox
from PIL import Image, ImageTk
import socket, threading, sys, traceback, os
import json
import time

from ClientStream import ClientStream 
from message import MensagemControlo, MensagemFlood

class Client:
	INIT = 0
	READY = 1
	PLAYING = 2

	state = INIT  # estado inicial

	SETUP = 0
	PLAY = 1
	PAUSE = 2
	TEARDOWN = 3
	
	def __init__(self, master,  client_ip, client_id, control_port, rtp_port, filename, bootstrapper_host, bootstrapper_port):	
		self.client_id = client_id													# ip do node
		self.client_ip = client_ip													# id do node
		self.node_type = "client"													# tipo do node: client
		self.porta_controlo = control_port											# porta de controlo

		self.filme = filename														# filme que vai receber
		self.porta_rtp = rtp_port													# porta para transmitir video
  
		self.vizinhos = {}															# dict para armazenar vizinhos ativos
		self.bootstrapper_ip = bootstrapper_host                                	# ip bootstrapper
		self.bootstrapper_porta = bootstrapper_port                             	# porta bootstrapper
        
		self.tabela_route = {}														# info sobre as rotas
		self.sessao_video = None													# objeto VideoSession
		self.pop_ip = None															# IP do pop que está a enviar video
		self.pop_rtsp_port = None													# porta RTSP do pop que está a enviar video

		self.master = master														# interface grafica

		self.lock = threading.Lock()												# por causa do multi-threading


	def start(self):
		self.bootstrapperRegister()
		threading.Thread(target=self.pinging).start()  
		threading.Thread(target=self.controlPart).start()  
		threading.Thread(target=self.initSession).start()  
		threading.Thread(target=self.monitorRotas).start() 


	"""
    @@@@@@ bootstrapper
    """	
	def bootstrapperRegister(self):
		"""
        regista o node no Bootstrapper e recebe a lista de vizinhos
        """
		# cria mensagem de controlo para registar o node
		mensagem_controlo = MensagemControlo()
		mensagem_controlo.type = MensagemControlo.MessageType.REGISTER
		mensagem_controlo.node_id = self.client_id
		mensagem_controlo.node_ip = self.client_ip
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
				
				print(f"Cliente {self.client_id} resgistado com sucesso!")    # debug

				# Limpa a lista de vizinhos 
				self.vizinhos.clear()	# casos de reativacao
				
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
				print(f"Node {self.client_id} | Vizinhos: {self.vizinhos}") # debug

				# notifica os vizinhos sobre o registo
				self.registrationNotify()
			
			else:
				print(f"Resposta recebida com o tipo Errado") #debug


	def registrationNotify(self):
		"""
        notifica os vizinhos que um node foi registado
        """
		# cria uma mensagem de controlo para enviar aos vizinhos
		mensagem_controlo = MensagemControlo()
		mensagem_controlo.type = MensagemControlo.MessageType.VIZINHOS_UPDATE
		mensagem_controlo.node_id = self.client_id
		mensagem_controlo.node_ip = self.client_ip
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

					print(f"Vizinho {info_vizinho['node_id']} notificado!") # debug

			except Exception as e:
				print(f"Erro: {e}") # debug
				

	"""
    @@@@@@ controlo
    """
	def controlPart(self):
		"""
        thread para conexões de outros nodes para pings e atualizações de vizinhos
        """
		# cria um socket para o "servidor de controlo"
		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as use_socket:
			
			use_socket.bind(('', self.porta_controlo))	# ip local e porta especificada
			
			use_socket.listen()	# aguarda conexões
			
			print(f"Cliente {self.client_id} ativo na porta de controlo: {self.porta_controlo}") # debug
			
			# loop infinito para aceitar conexoes de controle
			while True:
				connection, address = use_socket.accept()	# aceita conexao
				
				# cria thread para tratar
				threading.Thread(target=self.controlConnHandler, args=(connection, address)).start()
						

	def controlConnHandler(self, connection, address):
		"""
        trata conexões de controle de outros nodes
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
					
					# Se nao for MensagemControlo tlvz seja MensagemFlood
					try:
						mensagem_flood = MensagemFlood.ParseString_flood(data)
						
						# Se o tipo da mensagem for MensagemFlood
						if mensagem_flood.type == MensagemFlood.MessageType.FLOODING_UPDATE:
							print("MensagemFlood recebida") # debug
							self.updateTabelaRotas(mensagem_flood)
		
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
			
			print(f"Cliente {self.node_id} | Vizinhos: {self.vizinhos}") # debug
               
		
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
				
				mensagem_controlo = MensagemControlo()
				mensagem_controlo.type = MensagemControlo.MessageType.PING
				mensagem_controlo.node_ip = self.client_ip
				mensagem_controlo.node_id = self.client_id
				mensagem_controlo.node_type = self.node_type
				mensagem_controlo.control_port = self.porta_controlo
                
				use_socket.send(mensagem_controlo.Serialize().encode('utf-8')) 

				print(f"PING enviado para: {info_vizinho['node_id']}") # debug

				# Espera pela resposta (PING_RESPONSE)
				data = use_socket.recv(1024)
				if data:
					# cria mensagem de controlo (PING_RESPONSE)
					response_message = MensagemControlo.ParseString_control(data)

					if response_message.type == MensagemControlo.MessageType.PING_RESPONSE:
						print(f"PING_RESPONSE de: {response_message.node_id}") # debug
						
						# failed attempts resetado e status ativo
						with self.lock:
							info_vizinho["ping_falhados"] = 0
							info_vizinho["status"] = "ativo"

		except Exception as e:
			print(f"Ping falhado para o node: {info_vizinho['node_id']}: {e}")
			
			# Incrementa o nr de ping_falhados caso erro
			with self.lock:
				info_vizinho["ping_falhados"] = info_vizinho.get("ping_falhados", 0) + 1		


	def pingHandler(self, mensagem_controlo, conn):
		"""
        trata mensagens de ping recebidas e responde com mensagens de PING_RESPONSE
        """
		print(f"PING recebido de: {mensagem_controlo.node_id}") # debug

		# cria mensagem de controlo resposta
		mensagem_controlo = MensagemControlo()
		#mensagem_controlo.type = MensagemControlo.PING_RESPONSE ############
		mensagem_controlo.type = MensagemControlo.MessageType.PING_RESPONSE
		mensagem_controlo.node_id = self.client_ip
		mensagem_controlo.node_id = self.client_id
		mensagem_controlo.node_type = self.node_type
		mensagem_controlo.control_port = self.porta_controlo	

		conn.send(mensagem_controlo.Serialize().encode('utf-8'))
		
		print(f"PING_RESPONSE enviado para: {mensagem_controlo.node_id}") # debug
		
		# torna o status ativo e renicia os failed attempts para o node que enviou o ping
		with self.lock:
			if mensagem_controlo.node_ip in self.vizinhos:
					self.vizinhos[mensagem_controlo.node_ip]["status"] = "ativo"
					self.vizinhos[mensagem_controlo.node_ip]["ping_falhados"] = 0
	
	"""
    @@@@@ rotas
    """ 
	def updateTabelaRotas(self, mensagem_flood):
		"""
        atualiza a tabela de rotas com base na mensagem de flooding recebida
        """
		source_ip = mensagem_flood.source_ip		# node de origem da mensagem
		jumps = mensagem_flood.metrica				# metrica da mensagem de flood, numero de saltos no caso
		
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
						"flow": "inativa",
						"metrica": jumps,
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


	def initSession(self):
		"""
		Inicializa a sessão de vídeo com a melhor rota disponível no momento.
		"""
		# Loop para tentar encontrar e iniciar a melhor rota disponível
		while True:
			# tenta ativar um rota para filme
			melhor_rota = self.ativaRota(self.filme)
			
			if melhor_rota: 
				print("Rota Encontrada!") # debug

				# Atualiza os detalhes do destino com a melhor rota
				self.pop_ip = melhor_rota["source_ip"]
				self.pop_rtsp_port = melhor_rota["rtsp_port"]
				
				print("A iniciar interface gráfica..") # debug
				
				# Cria a interface gráfica para a sessão de vídeo
				self.janela = Toplevel(self.master)		# Nova janela para a sessão de vídeo
				self.frame = Frame(self.master)			# Frame para organizar os elementos da interface
				self.frame.pack()						# Adiciona o frame na janela principal
				
				# Cria e inicializa uma nova instância da sessão de vídeo
				self.sessao_video = ClientStream(self.janela, self.client_ip, self.pop_ip, self.pop_rtsp_port, self.porta_rtp, self.filme)
				
				# Adiciona um botão para fechar a sessão
				self.close_button = Button(
					self.frame, 
					text='Bom Filme!',										# Texto do botão 
					command=lambda: self.fechaSessao(self.sessao_video)		# Comando para fechar a sessão
				)	
				self.close_button.pack()									# Posiciona o botão na interface
				break  # Sai do loop após inicializar a sessão com sucesso
			
			else:
				# Caso não haja uma rota válida inicial, aguarda antes de tentar novamente
				print("Nova tentativa de inicar sessão em 20 segundos.")	
				time.sleep(20)  


	def ativaRota(self, filme):
		"""
        Ativa a melhor rota disponível na tabela de rotas com base na metrica
        """
		melhor_rota, destino = self.encontraMelhorRota(filme)
			
		if melhor_rota: # Se uma melhor rota foi encontrada
			with self.lock:
				# Atualiza o status da rota na tabela de roteamento como "ativa"
				self.tabela_route[destino][filme]['status'] = "ativo"

			print(f"Melhor Rota ativada: {melhor_rota['source_id']} com {melhor_rota['metrica']} saltos") # debug

			# Cria uma mensagem de flooding para ativar a rota
			mensagem_flood = MensagemFlood()
			mensagem_flood.type = MensagemFlood.MessageType.ATIVAR_ROTA
			mensagem_flood.id_filmes.append(filme)
			mensagem_flood.source_ip = self.client_ip
			mensagem_flood.rtp_port = self.porta_rtp
			
			# Tenta enviar a mensagem de ativação para o destino associado à melhor rota
			try:
				with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as use_socket: # TCP
					
					use_socket.connect((destino, melhor_rota['control_port']))

					use_socket.send(mensagem_flood.Serialize().encode('utf-8'))
					
					print(f"Mensagem de ativação enviada para: {melhor_rota['source_id']} para o filme {filme}.") # debug
					
					return self.tabela_route[destino][filme]
			
			except Exception as erro:
				print(f"Erro ao ativar rota para o destino {melhor_rota['source_id']} - {erro}") # debug
				return None
		
		else:
			print("Não há rotas disponiveis.") # debug
			return None
		

	def encontraMelhorRota(self, filme):
		"""
		Retorna a melhor rota e o destino associado, ou None se nenhuma rota válida for encontrada
		"""
		melhor_rota = None
		destino = None  

		min_metric = float('inf')  

		# Bloqueia a tabela de roteamento para acesso seguro
		with self.lock:
			# Itera sobre os destinos e suas rotas na tabela de roteamento
			for dest, route_info in self.tabela_route.items():
				
				# Verifica se o arquivo (fluxo) existe na tabela de rotas para o destino atual
				if filme in route_info:
					
					# Atualiza a melhor rota se a métrica for menor do que a menor encontrada até agora
					if route_info[filme]['metrica'] < min_metric:
						melhor_rota = route_info[filme]
						destino = dest
						min_metric = route_info[filme]['metrica']

		return melhor_rota, destino



	def fechaSessao(self, video_session):
		"""
		Fecha a sessão de vídeo atual e remove a janela e o botão associados
		"""
		print("A fechar sessão de video...") # debug

		# Verifica se a sessão de vídeo já está inativa
		if not video_session.active:  
			# Fecha a janela da sessão de vídeo, se ela ainda estiver aberta
			if self.janela:
				self.janela.destroy()	# Destroi a janela da interface gráfica
				self.janela = None  	# Remove a referência à janela

			# Remove o botão de "fechar sessão", se ele ainda existir
			if self.close_button:
				self.close_button.destroy()	# Remove o botão da interface gráfica
				self.close_button = None  	# Remove a referência ao botão,
			
			print("Sessão de video fechada!") # debug


	def monitorRotas(self):
		"""
		Monitor de rotas para verificar e ativar continuamente a melhor rota disponível.
		"""
		print("Monitoramento de rotas iniciado.")	# debug

		# loop infinito para monitoramento continuo
		while True:
			# tenta ativar a melhor rota para filme
			melhor_rota = self.ativaRota(self.filme)
			
			# Se uma nova rota for encontrada e ela for diferente da atual
			if melhor_rota and self.sessao_video is not None and melhor_rota["source_ip"] != self.pop_ip :
				print("Nova rota ativa encontrada! Atualizando a sessão de vídeo.") # debug
				
				# Atualiza o destino atual com os dados da nova rota
				self.pop_ip = melhor_rota["source_ip"]
				self.pop_rtsp_port = melhor_rota["rtsp_port"]
				
				# Atualiza a sessão de vídeo com o IP e porta do novo destino
				self.sessao_video.trocaRota(self.pop_ip, self.pop_rtsp_port)

				print(f"Sessão de vídeo atualizada para novo POP: {self.pop_ip}")  # debug
			
			time.sleep(30)  # Verifica a cada 30 segundos


"""
main
"""
if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python3 Client.py <clientX>.json")
        sys.exit(1)

    config_file = sys.argv[1]
    
    try:
        with open(config_file, 'r') as file:
            config = json.load(file)
    except Exception as e:
        print(f"Error reading config file: {e}")
        sys.exit(1)

    client_ip = config["client_ip"]
    client_id = config["client_id"]
    control_port = config["control_port"]
    rtp_port = config["rtp_port"]
    filme = config["filme"]
    bootstrapper_ip = config["bootstrapper_ip"]
    bootstrapper_port = config["bootstrapper_port"]

    root = Tk() # cria a janela pequena
	# depois quando é associada rota o ClientStream trata de anexar os widgets

    node = Client(
        root,
        client_ip,
        client_id,
        control_port,
        rtp_port,
        filme,
        bootstrapper_ip,
        bootstrapper_port,
    )

    node.start()
    
    root.mainloop()
