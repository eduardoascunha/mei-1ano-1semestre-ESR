from random import randint
import sys, traceback, threading, socket

from VideoStream import VideoStream
from RtpPacket import RtpPacket

"""
Codigo ligeiramente alterado para suportar envio de mais que 1 filme ao mesmo tempo.
"""
class ServerWorker:
	# Constantes para tipos de mensagens RTSP
	SETUP = 'SETUP'
	PLAY = 'PLAY'
	PAUSE = 'PAUSE'
	TEARDOWN = 'TEARDOWN'
	
	# Estados do servidor
	INIT = 0
	READY = 1
	PLAYING = 2
	state = INIT  # estado inicial

	# Códigos de resposta RTSP
	OK_200 = 0
	FILE_NOT_FOUND_404 = 1
	CON_ERR_500 = 2
	
	# Dicionário para armazenar informações sobre o cliente/router conectado
	clientInfo = {}
	

	def __init__(self, clientInfo):
		self.clientInfo = clientInfo


	# Método para iniciar a thread que recebe as requisições RTSP do cliente	
	def run(self):
		threading.Thread(target=self.recvRtspRequest).start()
	

	def recvRtspRequest(self):
		"""Receive RTSP request from the client."""
		connSocket = self.clientInfo['rtspSocket']
		while True:            
			data = connSocket.recv(256)	# Recebe dados do cliente
			if data:
				print("Data received:\n" + data.decode("utf-8") + "\n")
				self.processRtspRequest(data.decode("utf-8"))	# Processa a requisição RTSP
	

	def processRtspRequest(self, data):
		"""Process RTSP request sent from the client."""
		# Get the request type
		request = data.split('\n')
		line1 = request[0].split(' ')
		requestType = line1[0]

		print(f"Estado atual: {self.state}, tipo de mensagem: {requestType}")

		# Get the media file name
		filename = line1[1]
		
		if filename not in self.clientInfo:
			self.clientInfo[filename] = {}

		if 'state' not in self.clientInfo[filename]:		
			self.clientInfo[filename]['state'] = self.INIT
			self.clientInfo[filename]['session'] = filename

		# Get the RTSP sequence number 
		seq = request[1].split(' ')
		
		# Process SETUP request
		if requestType == self.SETUP:
			#if self.state == self.INIT:
			if self.clientInfo[filename]['state'] == self.INIT:
				print("processing SETUP\n")	# debug
				try:
					# Tenta abrir o arquivo de vídeo
					#self.clientInfo['videoStream'] = VideoStream(filename)
					self.clientInfo[filename]['videoStream'] = VideoStream(filename)
					#self.state = self.READY
					self.clientInfo[filename]['state'] = self.READY 

				except IOError:
					# Responde com erro 404 se o arquivo nao for encontrado
					#self.replyRtsp(self.FILE_NOT_FOUND_404, seq[1])
					self.replyRtsp(self.FILE_NOT_FOUND_404, seq[1], self.clientInfo[filename]['session']) 
				
				# Generate a randomized RTSP session ID
				#self.clientInfo['session'] = randint(100000, 999999)

				# Send RTSP OK reply
				#self.replyRtsp(self.OK_200, seq[1])
				self.replyRtsp(self.OK_200, seq[1], self.clientInfo[filename]['session'])

		# Process PLAY request 		
		elif requestType == self.PLAY:
			#if self.state == self.READY:
			if self.clientInfo[filename]['state'] == self.READY:
				print("processing PLAY\n") # debug
				
				#self.state = self.PLAYING
				self.clientInfo[filename]['state'] = self.PLAYING
				
				# Create a new socket for RTP/UDP
				#self.clientInfo['rtpSocket'] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
				self.clientInfo[filename]['rtpSocket'] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
				
				# Envia resposta RTSP OK
				#self.replyRtsp(self.OK_200, seq[1])
				self.replyRtsp(self.OK_200, seq[1], self.clientInfo[filename]['session'])
				
				# Create a new thread and start sending RTP packets
				#self.clientInfo['event'] = threading.Event()
				self.clientInfo[filename]['event'] = threading.Event()
				#self.clientInfo['worker']= threading.Thread(target=self.sendRtp)
				self.clientInfo[filename]['worker']= threading.Thread(target=self.sendRtp, args=(filename,))  
				#self.clientInfo['worker'].start()
				self.clientInfo[filename]['worker'].start()
		
		# Process PAUSE request
		elif requestType == self.PAUSE:
			#if self.state == self.PLAYING:
			if self.clientInfo[filename]['state'] == self.PLAYING:
				print("processing PAUSE\n")
				
				#self.state = self.READY
				self.clientInfo[filename]['state'] = self.READY

				# Para de enviar pacotes RTP
				#self.clientInfo['event'].set()
				self.clientInfo[filename]['event'].set()
			
				# Envia resposta RTSP OK
				#self.replyRtsp(self.OK_200, seq[1])
				self.replyRtsp(self.OK_200, seq[1], self.clientInfo[filename]['session'])
		
		# Process TEARDOWN request
		elif requestType == self.TEARDOWN:
			print("processing TEARDOWN\n")

			# Para de enviar pacotes RTP e encerra a conexão
			#self.clientInfo['event'].set()
			self.clientInfo[filename]['event'].set()
			
			# Envia resposta RTSP OK
			#self.replyRtsp(self.OK_200, seq[1])
			self.replyRtsp(self.OK_200, seq[1], self.clientInfo[filename]['session'])
			
			# Close the RTP socket
			#self.clientInfo['rtpSocket'].close()
			self.clientInfo[filename]['videoStream'].release() 
			self.clientInfo[filename]['rtpSocket'].close()


	def sendRtp(self, filename):
		"""Send RTP packets over UDP."""
		while True:
			#self.clientInfo['event'].wait(0.05) 
			self.clientInfo[filename]['event'].wait(0.05) 
			
			# Stop sending if request is PAUSE or TEARDOWN
			#if self.clientInfo['event'].isSet(): 
			if self.clientInfo[filename]['event'].isSet(): 
				break 
			
			# Obtém o próximo frame do vídeo	
			#data = self.clientInfo['videoStream'].nextFrame()
			data = self.clientInfo[filename]['videoStream'].nextFrame()
			
			if data: 
				#frameNumber = self.clientInfo['videoStream'].frameNbr()
				frameNumber = self.clientInfo[filename]['videoStream'].frameNbr()
				try:
					# Obtém o endereço IP e a porta para enviar o pacote RTP
					address = self.clientInfo['ip']

					print(f"Enviar pacote {frameNumber} do video {filename} em UDP para ADRESS :", address)
					
					port = int(self.clientInfo['rtp_port'])

					#self.clientInfo['rtpSocket'].sendto(self.makeRtp(data, frameNumber),(address, port))
					self.clientInfo[filename]['rtpSocket'].sendto(self.makeRtp(data, frameNumber, filename),(address, port))
				except:
					print("Connection Error")
					print('-'*60)
					traceback.print_exc(file=sys.stdout)
					print('-'*60)


	def makeRtp(self, payload, frameNbr, filename):
		"""RTP-packetize the video data."""
		version = 2
		padding = 0
		extension = 0
		cc = 0
		marker = 0
		pt = 26 # MJPEG type
		seqnum = frameNbr
		ssrc = 0 

		rtpPacket = RtpPacket()
		
		rtpPacket.encode(version, padding, extension, cc, seqnum, marker, pt, ssrc, payload, filename)
		
		return rtpPacket.getPacket()
		
		
	def replyRtsp(self, code, seq, session):
		"""Send RTSP reply to the client."""
		if code == self.OK_200:
			#reply = 'RTSP/1.0 200 OK\nCSeq: ' + seq + '\nSession: ' + str(self.clientInfo['session'])
			reply = 'RTSP/1.0 200 OK\nCSeq: ' + seq + '\nSession: ' + session
			
			#connSocket = self.clientInfo['rtspSocket'][0]
			connSocket = self.clientInfo['rtspSocket']
			connSocket.send(reply.encode())
		
		# Error messages
		elif code == self.FILE_NOT_FOUND_404:
			print("404 NOT FOUND")
		elif code == self.CON_ERR_500:
			print("500 CONNECTION ERROR")
