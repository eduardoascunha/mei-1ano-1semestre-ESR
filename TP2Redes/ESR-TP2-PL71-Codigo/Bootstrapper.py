import sys
import socket
import json
import threading

from message import MensagemControlo, VizinhoInfo

class Bootstrapper:
    def __init__(self, ip, porta, config_file):
        self.ip = ip
        self.porta = porta
        self.nodes = {} # dict para guardar info dos nodes registados 
        
        self.vizinhos_config = self.load_vizinhos(config_file)


    def load_vizinhos(self, config_file):
        """
        Carrega a configuração dos vizinhos a partir de um arquivo JSON
        """
        with open(config_file, 'r') as file:
            # load do json file
            neighbors_data = json.load(file)
        
        # converter JSON num formato de dict
        neighbors = {}
        for node in neighbors_data["nodes"]:
            # extrair o ID e o IP principal do node
            main_node_id = node["node_id"]
            main_node_ip = node["node_ip"]
            
            # extrair a lista de vizinhos
            neighbors_list = [
                (neighbor["neighbor_id"], neighbor["neighbor_ip"])
                for neighbor in node["neighbors"]
            ]
            
            # guardar no dict
            neighbors[main_node_ip] = {
                "node_id": main_node_id,
                "neighbors": neighbors_list
            }
        
        return neighbors
    

    def start(self):
        """
        Inicia o Bootstrapper
        """
        # cria um socket TCP
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as use_socket:
            use_socket.bind((self.ip, self.porta))  # associa o socket ao endereço e porta definidos
            use_socket.listen()                     # coloca o socket em modo de escuta
            
            print(f"Bootstrapper ativo - IP: {self.ip} | Porta: {self.porta}") # debug

            while True:
                # aceita uma nova conexao e cria uma thread para lidar com ela
                connection, _ = use_socket.accept()
                threading.Thread(target=self.client_handler, args=(connection,)).start()


    def client_handler(self, connection):
        """
        Lida com uma conexão de um node
        """
        try:
            data = connection.recv(1024)

            if data:
                mensagem_controlo = MensagemControlo.ParseString_control(data)

                if mensagem_controlo.type == MensagemControlo.MessageType.REGISTER:
                    self.register_handler(mensagem_controlo, connection)

        except Exception as erro:
            print(f"Ocorreu um erro ao processar a conexão - {erro}")
        
        finally:
            connection.close()
        

    def register_handler(self, mensagem_controlo, connection):
        """
        Lida com a solicitacao de registo de um node
        """
        node_id = mensagem_controlo.node_id
        node_ip = mensagem_controlo.node_ip
        node_type = mensagem_controlo.node_type
        control_port = mensagem_controlo.control_port

        # regista o node no dicionário de nodes
        self.nodes[node_ip] = {
            "node_id": node_id,
            "node_type": node_type,
            "control_port": control_port,
        }
        
        print(f"Node {node_id} registado - IP: {node_ip} | Porta de controlo:{control_port}") # Debug

        self.send_response(node_ip, connection)
    

    def send_response(self, node_ip, connection):
        """
        Cria e envia uma resposta de registo com os vizinhos ativos
        """
        mensagem_resposta = MensagemControlo()
        mensagem_resposta.type = MensagemControlo.MessageType.REGISTER_RESPONSE
        
        # se o ip registado tiver vizinhos ativos, adiciona os seus vizinhos ativos na resposta
        if node_ip in self.vizinhos_config:
            
            for neighbor_id, neighbor_ip in self.vizinhos_config[node_ip]["neighbors"]:
                
                if neighbor_ip in self.nodes:
                    # mensagem da classe VizinhoInfo()
                    vizinho_info = VizinhoInfo()
                    vizinho_info.node_id = neighbor_id
                    vizinho_info.node_ip = neighbor_ip
                    vizinho_info.node_type = self.nodes[neighbor_ip]["node_type"]
                    vizinho_info.control_port = self.nodes[neighbor_ip]["control_port"]
                    
                    # adiciona vizinho na resposta
                    mensagem_resposta.neighbors.append(vizinho_info) 
        
        # envia resposta com vizinhos
        connection.send(mensagem_resposta.Serialize().encode('utf-8'))
        
        print("Confirmacao de Registo enviada!")


"""
main
"""
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python3 Bootstrapper.py <bootstrapper>.json <cenario>.json")
        sys.exit(1)

    bootstrapper_file = sys.argv[1]

    try:
        with open(bootstrapper_file, 'r') as file:
            config = json.load(file)
    except FileNotFoundError:
        print(f"Error: Config file '{bootstrapper_file}' not found.")
        sys.exit(1)
      
    bootstrapper_ip = config.get("bootstrapper_ip")
    bootstrapper_port = config.get("bootstrapper_port")  

    config_file = sys.argv[2]

    # (ip, porta, config_file.json)
    bootstrapper = Bootstrapper(bootstrapper_ip, bootstrapper_port, config_file)
    bootstrapper.start()
