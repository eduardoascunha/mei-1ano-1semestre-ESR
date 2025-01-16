from tkinter import *
import tkinter.messagebox
from PIL import Image, ImageTk
import socket, threading, os

from RtpPacket import RtpPacket

CACHE_FILE_NAME = "cache-"
CACHE_FILE_EXT = ".jpg"

class ClientStream:
    INIT = 0
    READY = 1
    PLAYING = 2
    
    state = INIT # estado inicial

    SETUP = 0
    PLAY = 1
    PAUSE = 2
    TEARDOWN = 3
    
    def __init__(self, master, source_ip, pop_ip, porta_rtsp_pop, rtp_port, fileName):
        self.master = master
        
        self.client_ip = source_ip 
        self.pop_ip = pop_ip
        
        self.pop_porta_rtsp = porta_rtsp_pop
        self.socket_rtsp = None

        self.rtp_port = rtp_port 
        self.socket_rtp = None

        self.fileName = fileName

        self.rtspSeq = 0
        self.sessionId = None
        self.requestSent = -1
        self.teardownAcked = 0
        self.frameNbr = 0
        self.active = False 
        
        # conecta ao pop para iniciar stream
        self.popConnect()

        # cria interface
        self.createWidgets()


    def popConnect(self):
        """Inicia uma nova sessao RSTP"""
        self.socket_rtsp = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # TCP
        
        try:
            self.socket_rtsp.connect((self.pop_ip, self.pop_porta_rtsp))
        
        except Exception as erro:
            tkinter.messagebox.showwarning('Connection Failed', f"Erro ao conectar ao: '{self.pop_ip}': {erro}")
        
        
    def createWidgets(self):
        self.setup = Button(self.master, width=20, text="Setup", command=self.setupMovie)
        self.setup.grid(row=1, column=0, padx=2, pady=2)

        self.play = Button(self.master, width=20, text="Play", command=self.playMovie)
        self.play.grid(row=1, column=1, padx=2, pady=2)

        self.pause = Button(self.master, width=20, text="Pause", command=self.pauseMovie)
        self.pause.grid(row=1, column=2, padx=2, pady=2)

        self.teardown = Button(self.master, width=20, text="Teardown", command=self.exitClient)
        self.teardown.grid(row=1, column=3, padx=2, pady=2)
        
        self.label = Label(self.master, height=20)
        self.label.grid(row=0, column=0, columnspan=4, sticky=W+E+N+S, padx=5, pady=5)


    def setupMovie(self):
        """Setup button handler."""
        if self.state == self.INIT:
            self.sendRtspRequest(self.SETUP)


    def exitClient(self):
        """Teardown button handler."""
        self.sendRtspRequest(self.TEARDOWN)		
        self.master.destroy() # Close the gui window
        os.remove(CACHE_FILE_NAME + self.sessionId + CACHE_FILE_EXT) # Delete the cache image from video


    def pauseMovie(self):
        """Pause button handler."""
        if self.state == self.PLAYING:
            self.sendRtspRequest(self.PAUSE)


    def playMovie(self):
        """Play button handler."""
        if self.state == self.READY:
            # Create a new thread to listen for RTP packets
            threading.Thread(target=self.listenRtp).start()
            self.playEvent = threading.Event()
            self.playEvent.clear()
            self.sendRtspRequest(self.PLAY)


    def listenRtp(self):		
        """Listen for RTP packets."""
        while True:
            try:
                data = self.socket_rtp.recv(20480)
                if data:
                    rtpPacket = RtpPacket()
                    rtpPacket.decode(data)
                    
                    currFrameNbr = rtpPacket.seqNum()
                    print("Current Seq Num: " + str(currFrameNbr))
                                        
                    if currFrameNbr > self.frameNbr: # Discard the late packet
                        self.frameNbr = currFrameNbr
                        self.updateMovie(self.writeFrame(rtpPacket.getPayload()))
                    
            except:
                # Stop listening upon requesting PAUSE or TEARDOWN
                if self.playEvent.isSet(): 
                    break
                
                # Upon receiving ACK for TEARDOWN request,
                # close the RTP socket
                if self.teardownAcked == 1:
                    self.socket_rtp.shutdown(socket.SHUT_RDWR)
                    self.socket_rtp.close()
                    break
    

    def writeFrame(self, data):
        """Write the received frame to a temp image file. Return the image file."""
        cachename = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
        with open(cachename, "wb") as file:
            file.write(data)
        return cachename


    def updateMovie(self, imageFile):
        """Update the image file as video frame in the GUI."""
        photo = ImageTk.PhotoImage(Image.open(imageFile))
        self.label.configure(image = photo, height=288) 
        self.label.image = photo
        

    def sendRtspRequest(self, requestCode):
        """Send RTSP request to the server."""    
        # Setup request
        if requestCode == self.SETUP and self.state == self.INIT:
            threading.Thread(target=self.recvRtspReply).start()
            self.rtspSeq += 1
            #request = f"SETUP {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq}\n"
            request = f"SETUP {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq}\nIpCliente: {self.client_ip}\n" 
            self.requestSent = self.SETUP
        
        # Play request
        elif requestCode == self.PLAY and self.state == self.READY:
            self.rtspSeq += 1
            #request = f"PLAY {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq}\nSession: {self.sessionId}\n"
            request = f"PLAY {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq}\nSession: {self.sessionId}\nIpCliente: {self.client_ip}\n"
            self.requestSent = self.PLAY
            
        # Pause request
        elif requestCode == self.PAUSE and self.state == self.PLAYING:
            self.rtspSeq += 1
            #request = f"PLAY {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq}\nSession: {self.sessionId}\n"
            request = f"PAUSE {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq}\nSession: {self.sessionId}\nIpCliente: {self.client_ip}\n"
            self.requestSent = self.PAUSE
            
        # Teardown request
        elif requestCode == self.TEARDOWN and not self.state == self.INIT:
            self.rtspSeq += 1
            #request = f"PLAY {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq}\nSession: {self.sessionId}\n"
            request = f"TEARDOWN {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq}\nSession: {self.sessionId}\nIpCliente: {self.client_ip}\n"
            self.requestSent = self.TEARDOWN
        else:
            return
        
        # Send the RTSP request using rtspSocket.
        self.socket_rtsp.send(request.encode())

        print('\nData sent:\n' + request)


    def recvRtspReply(self):
        """Receive RTSP reply from the neighbor."""
        while True:
            reply = self.socket_rtsp.recv(1024)
            
            if reply: 
                self.parseRtspReply(reply.decode("utf-8"))
            
            # Close the RTSP socket upon requesting Teardown
            if self.requestSent == self.TEARDOWN:
                self.socket_rtsp.shutdown(socket.SHUT_RDWR)
                self.socket_rtsp.close()
                break


    def parseRtspReply(self, data):
        """Parse the RTSP reply from the server."""
        lines = data.split('\n')
        print(f"LINHES: {lines}\n")
        seqNum = int(lines[1].split(' ')[1])
        
        # Process only if the server reply's sequence number is the same as the request's
        if seqNum == self.rtspSeq:
            session = lines[2].split(' ')[1]
            # New RTSP session ID
            #if self.sessionId == 0:
            if self.sessionId == None:
                self.sessionId = session
            
            # Process only if the session ID is the same
            if self.sessionId == session:
                if int(lines[0].split(' ')[1]) == 200: 
                    if self.requestSent == self.SETUP:
                        self.state = self.READY	
                        self.openRtpPort() 
        
                    elif self.requestSent == self.PLAY:
                        self.state = self.PLAYING
                        print('\nPLAY sent\n')

                    elif self.requestSent == self.PAUSE:
                        self.state = self.READY
                        self.playEvent.set()

                    elif self.requestSent == self.TEARDOWN:
                        self.state = self.INIT
                        self.teardownAcked = 1 
                        self.active = False # fluxo desativado


    def openRtpPort(self):
        """Open RTP socket binded to a specified port."""
        self.socket_rtp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Set the timeout value of the socket to 0.5sec
        self.socket_rtp.settimeout(0.5)
        
        try:
            # Bind the socket to the address using the RTP port given by the client user
            self.socket_rtp.bind(('', self.rtp_port))
            print('\nBind to RTP port\n')
        except:
            tkinter.messagebox.showwarning('Unable to Bind', 'Unable to bind PORT=%d' %self.rtp_port)


    def handler(self):
        """Handler on explicitly closing the GUI window."""
        self.pauseMovie()
        if tkinter.messagebox.askokcancel("Quit?", "Are you sure you want to quit?"):
            self.exitClient()
        else: # When the user presses cancel, resume playing.
            self.playMovie()
            

    def trocaRota(self, new_pop_ip, new_rtsp_port):
        """
        Atualiza a sessão de vídeo para um novo IP e porta RTSP
        """
        self.pop_ip = new_pop_ip
        self.rtsp_port = new_rtsp_port
        
        print(f"Sessão de video atualizada para novo pop: {new_pop_ip}:{new_rtsp_port}") # debug