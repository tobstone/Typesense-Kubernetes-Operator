import os
import yaml
import logging
import datetime
from kubernetes.client.exceptions import ApiException


def validate_spec(op_spec: dict) -> dict:
    '''
    Function to validate the deployment yaml spec
    Param:
        op_spec : dict -> operator yaml file spec
    '''
    spec = op_spec['new'].get('spec', None)
    config = op_spec['new'].get('config', None)
    return_data = {}
    if spec:
        if spec.get('resources'):
            if spec.get('requests'):
                if not spec.get('memory') or spec.get('cpu'):
                    raise Exception("Memory or cpu is missing under requests")
            if spec.get('limits'):
                if not spec.get('memory') or spec.get('cpu'):
                    raise Exception("Memory or cpu is missing under limits")
        return_data['namespace'] = spec.get('namespace', 'typesense')
        return_data['image'] = spec.get('image', 'typesense/typesense')
        return_data['resources'] = spec.get('resources', None)
        return_data['host'] = spec.get('host', 'typesense.dwbn.local')
        return_data['nodeSelector'] = spec.get('nodeSelector', None)
        return_data['clusterdomain'] = spec.get(
            'clusterdomain', 'cluster.local')
        return_data['replicas'] = spec.get('replicas', 3)
        if spec.get('storageClass'):
            if not spec['storageClass'].get('name') or not spec['storageClass'].get('size'):
                raise Exception('Missing storageClass name or size')
            return_data['storageClassName'] = spec['storageClass']['name']
            return_data['storage'] = spec['storageClass']['size']

    if config:
        return_data['password'] = config.get('password', '297beb01dd21c')
    return return_data


def create_modify_namespace(core_obj: object, namespace='default') -> None:
    '''
    Function to create or modify namespace
    Params:
        core_obj: kubernetes CoreV1Api object
    '''
    try:
        path = os.path.join(
            os.path.dirname(__file__),
            'templates/namespace.yaml'
        )
        configuration = None
        with open(path, 'r') as _file:
            configuration = yaml.safe_load(_file)
        if namespace != 'default':
            configuration['metadata']['name'] = namespace
        try:
            resp = core_obj.create_namespace(body=configuration)
            logging.info(
                f"Created namespace {resp.metadata.name} successfully")
        except ApiException as e:
            logging.error(f"Kubernets Api Exception - Namespace: {e.body} ")
            raise Exception(f"Kubernets Api Exception - Namespace: {e.body}")
    except Exception as e:
        logging.error(f"Exception namespace: {e}")
        raise Exception(f"Exception namespace: {e}")


def deploy_typesense_statefulset(apps_obj: object, spec: dict, update=False) -> None:
    '''
    Function to deploy Typesense statefulset
    Params:
        apps_obj: kubernetes AppsV1Api object
    '''
    try:
        path = os.path.join(
            os.path.dirname(__file__),
            'templates/statefulset.yaml'
        )
        configuration = None
        with open(path, 'r') as _file:
            configuration = yaml.safe_load(_file)
        if spec.get('storageClassName'):
            template = {
                "volumeClaimTemplates": [
                    {
                        "metadata": {
                            "name": "data"
                        },
                        "spec": {
                            "accessModes": [
                                "ReadWriteOnce"
                            ],
                            "storageClassName": spec['storageClassName'],
                            "resources": {
                                "requests": {
                                    "storage": spec['storage']
                                }
                            }
                        }
                    }
                ]
            }
            configuration['spec']['volumeClaimTemplates'] = template['volumeClaimTemplates']
        else:
            # Use empty dir mount
            configuration['spec']['template']['spec']['volumes'].append(
                {"name": "data", "emptyDir": {"sizeLimit": "500Mi"}})
        configuration['metadata']['namespace'] = spec['namespace']
        if spec.get('image'):
            configuration['spec']['template']['spec']['containers'][0]['image'] = spec['image']
        if spec.get('resources'):
            configuration['spec']['template']['spec']['containers'][0]['resources'] = spec['resources']
        if spec.get('nodeSelector'):
            configuration['spec']['template']['spec']['nodeSelector'] = spec['nodeSelector']
        if spec.get('password'):
            configuration['spec']['template']['spec']['containers'][0]['command'][4] = spec['password']
        if spec.get('replicas'):
            configuration['spec']['replicas'] = spec['replicas']
        if update:
            configuration["spec"]["template"]["metadata"]["annotations"] = {
                "kubectl.kubernetes.io/restartedAt": datetime.datetime.utcnow().isoformat()
            }
            apps_obj.patch_namespaced_stateful_set(
                body=configuration, name="typesense", namespace=spec['namespace'])
        else:
            apps_obj.create_namespaced_stateful_set(
                body=configuration, namespace=spec['namespace'])
    except ApiException as e:
        logging.error(f"Kubernets Api Exception - Statefulset: {e.body} ")
        raise Exception(f"Kubernets Api Exception - Statefulset: {e.body} ")
    except Exception as e:
        logging.error(f"Exception statefulset: {e}")
        raise Exception(f"Exception statefulset: {e}")


def deploy_configmap(core_obj: object, replicas=None, namespace='default', update=False, clusterdomain='cluster.local') -> None:
    '''
    Function to create configmap used by Typesense
    Params:
        core_obj: kubernetes CoreV1Api object
    '''
    try:
        nodes = []
        path = os.path.join(
            os.path.dirname(__file__),
            'templates/configmap.yaml'
        )
        configuration = None
        with open(path, 'r') as _file:
            configuration = yaml.safe_load(_file)
        configuration['metadata']['namespace'] = namespace
        if replicas:
            for count in range(0, int(replicas)):
                nodes.append(
                    ('typesense-{}.ts.{}.svc.{}:8107:8108').format(str(count), namespace, clusterdomain))
            configuration['data']['nodes'] = ','.join(nodes)
        if update:
            core_obj.patch_namespaced_config_map(
                body=configuration, namespace=namespace, name="nodeslist")
        else:
            core_obj.create_namespaced_config_map(
                body=configuration, namespace=namespace)
        logging.info(f"Created Configmap nodeslist successfully")
    except ApiException as e:
        logging.error(f"Kubernets Api Exception - Configmap: {e.body} ")
        raise Exception(f"Kubernets Api Exception - Configmap: {e.body} ")
    except Exception as e:
        logging.error(f"Exception configmap: {e}")
        raise Exception(f"Exception configmap: {e}")


def deploy_service(core_obj: object, namespace='default') -> None:
    '''
    Function to deploy service mapping to connect with Typesense
    Params:
        core_obj: kubernetes CoreV1Api object
    '''
    try:
        '''
        ----Deploy service---
        '''
        service_path = os.path.join(
            os.path.dirname(__file__),
            'templates/service.yaml'
        )
        configuration = None
        with open(service_path, 'r') as _file:
            configuration = yaml.safe_load(_file)
        configuration['metadata']['namespace'] = namespace
        resp = core_obj.create_namespaced_service(
            body=configuration, namespace=namespace)

        logging.info(f"Created Service {resp.metadata.name} successfully")

        '''
        ----Deploy headless service---
        '''
        headless_service_path = os.path.join(
            os.path.dirname(__file__),
            'templates/headless-service.yaml'
        )
        with open(headless_service_path, 'r') as _file:
            configuration = yaml.safe_load(_file)
        configuration['metadata']['namespace'] = namespace
        resp = core_obj.create_namespaced_service(
            body=configuration, namespace=namespace)

        logging.info(
            f"Created Headless Service {resp.metadata.name} successfully")
    except ApiException as e:
        logging.error(f"Kubernets Api Exception - Service: {e.body} ")
        raise Exception(f"Kubernets Api Exception - Service: {e.body} ")
    except Exception as e:
        logging.error(f"Exception service: {e}")
        raise Exception(f"Exception service: {e}")


def deploy_ingress(networking_obj: object, namespace='default', host='typesense.dwbn.local', update=False) -> None:
    '''
    Funstion to deploy Ingress
    Params:
        networking_obj: kubernetes NetworkingV1Api
    '''
    try:
        ingress_path = os.path.join(
            os.path.dirname(__file__),
            'templates/ingress.yaml'
        )
        with open(ingress_path, 'r') as _file:
            configuration = yaml.safe_load(_file)
        configuration['metadata']['namespace'] = namespace
        configuration['spec']['rules'][0]['host'] = host

        if update:
            networking_obj.patch_namespaced_ingress(
                body=configuration, name="typesense", namespace=namespace)
        else:
            networking_obj.create_namespaced_ingress(
                body=configuration, namespace=namespace)
        logging.info(
            f"Created Ingress successfully")
    except ApiException as e:
        logging.error(f"Kubernets Api Exception - Ingress: {e.body} ")
        raise Exception(f"Kubernets Api Exception - Ingress: {e.body} ")
    except Exception as e:
        logging.error(f"Exception Ingress: {e}")
        raise Exception(f"Exception Ingress: {e}")


def cleanup(core_obj: object, namespace='default') -> None:
    '''
    Function to cleanup all resources
    Params:
        core_obj: kubernetes CoreV1Api object
    '''
    try:
        core_obj.delete_namespace(namespace)
    except ApiException as e:
        logging.error(f"Kubernets Api Exception - Cleanup: {e.body} ")
        raise Exception(f"Kubernets Api Exception - Cleanup: {e.body} ")
    except Exception as e:
        logging.error(f"Exception Cleanup: {e}")
        raise Exception(f"Exception Cleanup: {e}")
