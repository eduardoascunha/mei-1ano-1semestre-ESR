
"""
@@@@@ Controlo
"""
class MensagemControlo:
    
    class MessageType:
        REGISTER = 0
        REGISTER_RESPONSE = 1
        VIZINHOS_UPDATE = 2
        PING = 3
        PING_RESPONSE = 4

    def __init__(self, message_type=None, node_ip="", node_id="", node_type="", neighbors=None, control_port=0):
        self.type = message_type if message_type is not None else MensagemControlo.MessageType.REGISTER
        self.node_ip = node_ip
        self.node_id = node_id
        self.node_type = node_type
        self.control_port = control_port
        self.neighbors = neighbors if neighbors is not None else []

    def add_neighbor(self, neighbor_info):
        self.neighbors.append(neighbor_info)

    def Serialize(self):
        """
        Serializa os atributos da instância numa string formatada, mas sem o "encode"
        """
        neighbors_str = ', '.join([f"{n.node_id}({n.node_ip}:{n.control_port})" for n in self.neighbors])
        return f"type={self.type};node_ip={self.node_ip};node_id={self.node_id};node_type={self.node_type};control_port={self.control_port};neighbors=[{neighbors_str}]"
    
    @classmethod
    def ParseString_control(cls, data_string):
        """
        Converte uma string formatada numa instância de `MensagemControlo`
        """
        if isinstance(data_string, bytes):
            data_string = data_string.decode('utf-8')

        fields = data_string.split(';')
        params = {}
        for field in fields:
            key, value = field.split('=')
            params[key.strip()] = value.strip()

        neighbors_str = params.get('neighbors', '[]').strip('[]')
        neighbors = []
        if neighbors_str:
            neighbor_entries = neighbors_str.split(', ')
            for entry in neighbor_entries:
                try:
                    node_id, rest = entry.split('(')
                    node_ip, control_port = rest.strip(')').split(':')
                    neighbors.append(VizinhoInfo(node_id=node_id, node_ip=node_ip, control_port=int(control_port)))
                except ValueError:
                    continue

        return cls(
            message_type=int(params.get('type', cls.MessageType.REGISTER)),
            node_ip=params.get('node_ip', ""),
            node_id=params.get('node_id', ""),
            node_type=params.get('node_type', ""),
            control_port=int(params.get('control_port', 0)),
            neighbors=neighbors
        )

    def __str__(self):
        neighbors_str = ', '.join(str(neighbor) for neighbor in self.neighbors)
        return (f"MensagemControlo(type={self.type}, node_ip={self.node_ip}, node_id={self.node_id}, "
                f"node_type={self.node_type}, control_port={self.control_port}, "
                f"neighbors=[{neighbors_str}])")

"""
@@@@@ Vizinhos
"""
class VizinhoInfo:
    def __init__(self, node_id="", node_ip="", node_type="", control_port=0):
        self.node_id = node_id
        self.node_ip = node_ip
        self.node_type = node_type 
        self.control_port = control_port

    def __str__(self):
        return (f"VizinhoInfo(node_id={self.node_id}, node_ip={self.node_ip}, "
                f"node_type={self.node_type}, control_port={self.control_port})")

"""
@@@@@ Flood
"""
class MensagemFlood:
    
    class MessageType:
        FLOODING_UPDATE = 0
        ATIVAR_ROTA = 1

    def __init__(self, message_type=None, source_id="", id_filmes=None, source_ip="", estado_rota="", metrica=0, control_port=0, rtsp_port=0, rtp_port=0):
        self.type = message_type if message_type is not None else MensagemFlood.MessageType.FLOODING_UPDATE
        self.source_id = source_id
        self.source_ip = source_ip
        self.id_filmes = id_filmes if id_filmes is not None else []
        self.estado_rota = estado_rota
        self.metrica = metrica
        self.control_port = control_port
        self.rtsp_port = rtsp_port
        self.rtp_port = rtp_port

    def Serialize(self):
        """
        Serializa os atributos da instância em uma string formatada, mas sem o "encode"
        """
        id_filmes_str = ','.join(self.id_filmes)
        return (f"type={self.type};source_id={self.source_id};id_filmes=[{id_filmes_str}];source_ip={self.source_ip};"
                f"estado_rota={self.estado_rota};metrica={self.metrica};control_port={self.control_port};"
                f"rtsp_port={self.rtsp_port};rtp_port={self.rtp_port}")
    
    @classmethod
    def ParseString_flood(cls, data_string):
        """
        Converte uma string formatada numa instância de `MensagemFlood`
        """
        if isinstance(data_string, bytes):
            data_string = data_string.decode('utf-8')

        fields = data_string.split(';')
        params = {}
        for field in fields:
            key, value = field.split('=')
            params[key.strip()] = value.strip()

        id_filmes_str = params.get('id_filmes', '[]').strip('[]')
        id_filmes = id_filmes_str.split(',') if id_filmes_str else []

        return cls(
            message_type=int(params.get('type', cls.MessageType.FLOODING_UPDATE)),
            source_id=params.get('source_id', ""),
            id_filmes=id_filmes,
            source_ip=params.get('source_ip', ""),
            estado_rota=params.get('estado_rota', ""),
            metrica=int(params.get('metrica', 0)),
            control_port=int(params.get('control_port', 0)),
            rtsp_port=int(params.get('rtsp_port', 0)),
            rtp_port=int(params.get('rtp_port', 0))
        )

    def __str__(self):
        return (f"MensagemFlood(type={self.type}, source_id={self.source_id}, id_filmes={self.id_filmes}, "
                f"source_ip={self.source_ip}, estado_rota={self.estado_rota}, metrica={self.metrica}, "
                f"control_port={self.control_port}, rtsp_port={self.rtsp_port}, rtp_port={self.rtp_port})")