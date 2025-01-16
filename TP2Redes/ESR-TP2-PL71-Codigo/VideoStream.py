class VideoStream:
    def __init__(self, filename):
        """
        Inicializa a classe VideoStream.

        :param filename: O nome do arquivo de vídeo a ser lido.
        """
        self.filename = filename  # Armazena o nome do arquivo

        try:
            self.file = open(filename, 'rb')  # Tenta abrir o arquivo em modo leitura binária
        except FileNotFoundError:
            raise IOError(f"Arquivo {filename} não encontrado.")  # Lança exceção se não conseguir abrir o arquivo

        self.frameNum = 0  # Inicializa o contador de quadros em 0

    def nextMJPEGFrame(self):
        """
        Obtém o próximo quadro MJPEG do arquivo.

        :return: Os dados do próximo quadro JPEG ou None se o final do arquivo for alcançado.
        """
        frame_data = bytearray()
        while True:
            byte = self.file.read(1)  # Lê o arquivo byte a byte
            if not byte:
                # EOF alcançado
                return None if not frame_data else ValueError("Quadro incompleto no final do arquivo.")
            frame_data += byte
            # Verifica se encontrou o final de um quadro JPEG (FF D9)
            if frame_data[-2:] == b'\xFF\xD9':
                self.frameNum += 1
                return bytes(frame_data)

    def nextFrame(self):
        """
        Obtém o próximo quadro do arquivo no formato MJPEG.

        :return: Dados do próximo quadro lido do arquivo ou None se não houver mais quadros.
        """
        return self.nextMJPEGFrame()

    def frameNbr(self):
        """
        Obtém o número atual do quadro.

        :return: O número do quadro atual.
        """
        return self.frameNum  # Retorna o contador de quadros atual

    def release(self):
        """
        Libera o arquivo de vídeo, fechando-o se estiver aberto.
        """
        if not self.file.closed:  # Verifica se o arquivo ainda está aberto
            self.file.close()  # Fecha o arquivo