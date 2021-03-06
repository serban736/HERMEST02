import sys
import socket
import os
from datetime import datetime
import emoji
import logging
import requests
# gRPC stuff
import grpc
from six import b
import whereami_pb2
import whereami_pb2_grpc

METADATA_URL = 'http://metadata.google.internal/computeMetadata/v1/'
METADATA_HEADERS = {'Metadata-Flavor': 'Google'}

# set up emoji list
emoji_list = list(emoji.unicode_codes.UNICODE_EMOJI['en'].keys())


class WhereamiPayload(object):

    def __init__(self):

        self.payload = {}

    def build_payload(self, request_headers):

        # header propagation for HTTP calls to downward services
        # for Istio / Anthos Service Mesh
        def getForwardHeaders(request_headers):
            headers = {}
            incoming_headers = ['x-request-id',
                                'x-b3-traceid',
                                'x-b3-spanid',
                                'x-b3-parentspanid',
                                'x-b3-sampled',
                                'x-b3-flags',
                                'x-ot-span-context',
                                'x-cloud-trace-context',
                                'traceparent',
                                'grpc-trace-bin'
                                ]

            for ihdr in incoming_headers:
                val = request_headers.get(ihdr)
                if val is not None:
                    headers[ihdr] = val

            return headers

        # call HTTP backend (expect JSON reesponse)
        def call_http_backend(backend_service):

            try:
                r = requests.get(backend_service,
                                 headers=getForwardHeaders(request_headers))
                if r.ok:
                    backend_result = r.json()
                else:
                    backend_result = None
            except:

                logging.warning(sys.exc_info()[0])
                backend_result = None

            return backend_result

        # call gRPC backend
        def call_grpc_backend(backend_service):

            try:
                channel = grpc.insecure_channel(backend_service +
                                                ':9090')
                stub = whereami_pb2_grpc.WhereamiStub(channel)
                backend_result = stub.GetPayload(
                    whereami_pb2.Empty())

            except:
                backend_result = None
                logging.warning("Unable to capture backend result.")

            return backend_result

        # get GCP project ID
        try:
            r = requests.get(METADATA_URL + 'project/project-id',
                             headers=METADATA_HEADERS)
            if r.ok:
                self.payload['project_id'] = r.text
        except:

            logging.warning("Unable to capture project ID.")

        # get GCP zone
        try:
            r = requests.get(METADATA_URL + 'instance/zone',
                             headers=METADATA_HEADERS)
            if r.ok:
                self.payload['zone'] = str(r.text.split("/")[3])
        except:

            logging.warning("Unable to capture zone.")

        # get node name via downward API
        if os.getenv('NODE_NAME'):
            self.payload['node_name'] = os.getenv('NODE_NAME')
        else:
            logging.warning("Unable to capture node name.")

        # get GKE cluster name
        try:
            r = requests.get(METADATA_URL +
                             'instance/attributes/cluster-name',
                             headers=METADATA_HEADERS)
            if r.ok:
                self.payload['cluster_name'] = str(r.text)
        except:

            logging.warning("Unable to capture GKE cluster name.")

        # get host header
        try:
            self.payload['host_header'] = request_headers.get('host')
        except:
            logging.warning("Unable to capture host header.")

        # get pod name, emoji & datetime
        self.payload['pod_name'] = socket.gethostname()
        self.payload['pod_name_emoji'] = emoji_list[hash(
            socket.gethostname()) % len(emoji_list)]
        self.payload['timestamp'] = datetime.now().replace(
            microsecond=0).isoformat()

        # get namespace, pod ip, and pod service account via downward API
        if os.getenv('POD_NAMESPACE'):
            self.payload['pod_namespace'] = os.getenv('POD_NAMESPACE')
        else:
            logging.warning("Unable to capture pod namespace.")

        if os.getenv('POD_IP'):
            self.payload['pod_ip'] = os.getenv('POD_IP')
        else:
            logging.warning("Unable to capture pod IP address.")

        if os.getenv('POD_SERVICE_ACCOUNT'):
            self.payload['pod_service_account'] = os.getenv(
                'POD_SERVICE_ACCOUNT')
        else:
            logging.warning("Unable to capture pod KSA.")

        # get the whereami METADATA envvar
        if os.getenv('METADATA'):
            self.payload['metadata'] = os.getenv('METADATA')
        else:
            logging.warning("Unable to capture metadata.")

        # should we call a backend service?
        if os.getenv('BACKEND_ENABLED') == 'True':

            print("making a call")
            backend_service = os.getenv('BACKEND_SERVICE')

            if os.getenv('GRPC_ENABLED') == "True":

                backend_result = call_grpc_backend(backend_service)

                if backend_result:

                    self.payload['backend_result'] = backend_result

            else:

                self.payload['backend_result'] = call_http_backend(backend_service)

        echo_headers = os.getenv('ECHO_HEADERS')

        if echo_headers == 'True':

            try:

                self.payload['headers'] = {k: v for k, v in request_headers.items()}

            except:

                logging.warning("Unable to capture inbound headers.")

        return self.payload
