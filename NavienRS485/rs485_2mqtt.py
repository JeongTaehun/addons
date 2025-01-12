import paho.mqtt.client as mqtt
import re
from json import dumps as json_dumps
from functools import reduce
from collections import defaultdict
import json

MQTT_USERNAME = 'dojuckno'
MQTT_PASSWORD = 'za8153275!'
MQTT_SERVER = '172.30.1.16'
MQTT_PORT = 1883
ROOT_TOPIC_NAME = 'rs485_mqtt'
HOMEASSISTANT_ROOT_TOPIC_NAME = 'homeassistant'

class Device:
    def __init__(self, device_name, device_id, device_subid, device_class, child_devices, mqtt_discovery, optional_info):
        self.device_name = device_name
        self.device_id = device_id
        self.device_subid = device_subid
        self.device_unique_id = f'rs485_{self.device_id}_{self.device_subid}'
        self.device_class = device_class
        self.child_devices = child_devices
        self.mqtt_discovery = mqtt_discovery
        self.optional_info = optional_info

        self.status_messages = defaultdict(list)
        self.command_messages = {}

    def register_status(self, message_flag, attr_name, regex, topic_class, device_name=None, process_func=lambda v: v):
        device_name = device_name or self.device_name
        self.status_messages[message_flag].append({
            'regex': regex, 'process_func': process_func, 
            'device_name': device_name, 'attr_name': attr_name, 
            'topic_class': topic_class
        })

    def register_command(self, message_flag, attr_name, topic_class, controll_id=None, process_func=lambda v: v):
        self.command_messages[attr_name] = {
            'message_flag': message_flag, 'attr_name': attr_name, 
            'topic_class': topic_class, 'process_func': process_func,
            'controll_id': controll_id
        }

    def parse_payload(self, payload_dict):
        result = {}
        for status in self.status_messages[payload_dict['message_flag']]:
            parse_status = re.match(status['regex'], payload_dict['data'])
            # print(status['regex'], payload_dict['data'])
            # print(parse_status)
            if len(self.child_devices)>0:
                for index, child_device in enumerate(self.child_devices):
                    topic = f"{ROOT_TOPIC_NAME}/{self.device_class}/{child_device}{self.device_name}/{status['attr_name']}"
                    # climate일 경우 비트연산으로 예외발생..                    
                    if (status['attr_name']=="power" or status['attr_name']=="away_mode") and self.device_class=="climate":
                        result[topic] = status['process_func'](int(parse_status.group(1), 16) & (1 << index))
                    else:
                        result[topic] = status['process_func'](parse_status.group(index+1))
                    
            else:
                topic = f"{ROOT_TOPIC_NAME}/{self.device_class}/{self.device_name}/{status['attr_name']}"    
                result[topic] = status['process_func'](parse_status.group(1))
                # print(result[topic])
        return result

    def get_command_payload(self, attr_name, attr_value, child_name=None):
        # print(self.device_name, self.device_subid, attr_value)
        attr_value = self.command_messages[attr_name]['process_func'](attr_value)
        if child_name is not None:
            idx = [child + self.device_name for child in self.child_devices].index(child_name)
            # print(self.child_devices,idx,self.command_messages[attr_name]['controll_id'][idx])
            command_payload = ['f7', self.device_id, self.command_messages[attr_name]['controll_id'][idx],
                            self.command_messages[attr_name]['message_flag'], '01', attr_value]
        # 예외처리 엘베 호출
        elif self.device_id=='33' and self.command_messages[attr_name]['message_flag']=='81':
            command_payload = ['f7', self.device_id, self.device_subid,
                            self.command_messages[attr_name]['message_flag'], '03', '00', attr_value, '00']
        else:            
            command_payload = ['f7', self.device_id, self.device_subid,
                            self.command_messages[attr_name]['message_flag'], '00']
        # print(self.command_messages[attr_name]['message_flag'])
        # print(command_payload)
        command_payload.append(Wallpad.xor(command_payload))
        command_payload.append(Wallpad.add(command_payload))
        # print(command_payload)
        # print(bytearray.fromhex(' '.join(command_payload)))
        return bytearray.fromhex(' '.join(command_payload))

    def get_mqtt_discovery_payload(self):        
        discovery_list = list()
        if len(self.child_devices)>0:            
            for idx, child in enumerate(self.child_devices):
                unique_id_join = self.device_unique_id + str(idx)
                device_name_join = child + self.device_name;
                # print(unique_id_join, device_name_join)
                topic = f"{HOMEASSISTANT_ROOT_TOPIC_NAME}/{self.device_class}/{unique_id_join}/config"
                result = {
                    '~': f"{ROOT_TOPIC_NAME}/{self.device_class}/{device_name_join}",
                    'name': device_name_join,
                    'uniq_id': unique_id_join,
                    'device_class' : self.device_class,
                }
                result.update(self.optional_info)
                for status_list in self.status_messages.values():
                    for status in status_list:
                        result[status['topic_class']] = f"~/{status['attr_name']}"

                for status_list in self.command_messages.values():
                    result[status_list['topic_class']] = f"~/{status_list['attr_name']}/set"

                result['device'] = {
                    'identifiers': unique_id_join,
                    'name': device_name_join
                }
                discovery_list.append((topic, json_dumps(result, ensure_ascii=False)))
        else:
            topic = f"{HOMEASSISTANT_ROOT_TOPIC_NAME}/{self.device_class}/{self.device_unique_id}/config"            
            result = {
                '~': f"{ROOT_TOPIC_NAME}/{self.device_class}/{self.device_name}",
                'name': self.device_name,
                'uniq_id': self.device_unique_id,
            }
            result.update(self.optional_info)
            for status_list in self.status_messages.values():
                for status in status_list:
                    result[status['topic_class']] = f"~/{status['attr_name']}"

            for status_list in self.command_messages.values():
                result[status_list['topic_class']] = f"~/{status_list['attr_name']}/set"

            result['device'] = {
                'identifiers': self.device_unique_id,
                'name': self.device_name
            }
            discovery_list.append((topic, json_dumps(result, ensure_ascii=False)))
            
        return discovery_list
    def get_status_attr_list(self):
        return list(set(status['attr_name'] for status_list in self.status_messages.values() for status in status_list))


class Wallpad:
    def __init__(self):
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt_client.on_message = self.on_raw_message
        self.mqtt_client.on_disconnect = self.on_disconnect
        self.mqtt_client.username_pw_set(username=MQTT_USERNAME, password=MQTT_PASSWORD)
        self.mqtt_client.connect(MQTT_SERVER, 1883)
        self._device_list = []

    def listen(self):
        self.register_mqtt_discovery()
        for topic_list in [(topic, 2) for topic in [f"{ROOT_TOPIC_NAME}/dev/raw"] + self.get_topic_list_to_listen()]:
            print(topic_list)
        self.mqtt_client.subscribe([(topic, 2) for topic in [f"{ROOT_TOPIC_NAME}/dev/raw"] + self.get_topic_list_to_listen()])
        self.mqtt_client.loop_forever()

    def register_mqtt_discovery(self):
        for device in self._device_list:
            if device.mqtt_discovery:                
                for topic, payload in device.get_mqtt_discovery_payload():
                    self.mqtt_client.publish(topic, payload, qos=2, retain=True)

    def add_device(self, device_name, device_id, device_subid, device_class, child_devices=[], mqtt_discovery=True, optional_info={}):
        device = Device(device_name, device_id, device_subid, device_class, child_devices, mqtt_discovery, optional_info)
        self._device_list.append(device)
        return device

    def get_device(self, **kwargs):
        device = next((d for d in self._device_list if 
                       d.device_name == kwargs.get('device_name') or 
                       kwargs.get('device_name') in [child + d.device_name for child in d.child_devices] or
                      (d.device_id == kwargs.get('device_id') and d.device_subid == kwargs.get('device_subid'))), None)
        if device:
            return device
        else:
            raise ValueError(f"Device with id {kwargs.get('device_id')} and subid {kwargs.get('device_subid')} not found.")

    def get_topic_list_to_listen(self):
        return [f"{ROOT_TOPIC_NAME}/{device.device_class}/{child_name}{device.device_name}/{attr_name}/set" 
                for device in self._device_list 
                for child_name in (device.child_devices if device.child_devices else [""])  # child_devices가 없는 경우 빈 문자열 사용
                for attr_name in device.get_status_attr_list()]

    @classmethod
    def xor(cls, hexstring_array):
        return format(reduce(lambda x, y: x ^ y, map(lambda x: int(x, 16), hexstring_array)), '02x')

    @classmethod
    def add(cls, hexstring_array):
        return format(reduce(lambda x, y: x + y, map(lambda x: int(x, 16), hexstring_array)), '02x')[-2:]

    @classmethod
    def is_valid(cls, payload_hexstring):
        payload_array = [payload_hexstring[i:i+2] for i in range(0, len(payload_hexstring), 2)]
        try:
            valid = int(payload_array[4], 16) + 7 == len(payload_array) and \
                    cls.xor(payload_array[:-2]) == payload_array[-2:-1][0] and \
                    cls.add(payload_array[:-1]) == payload_array[-1:][0]
            return valid
        except:
            return False

    def on_raw_message(self, client, userdata, msg):
        if msg.topic == f"{ROOT_TOPIC_NAME}/dev/raw":
            self._process_raw_message(client, msg)
        else:
            print(msg.topic)    
            self._process_command_message(client, msg)

    def _process_raw_message(self, client, msg):
        for payload_raw_bytes in msg.payload.split(b'\xf7')[1:]:
            payload_hexstring = 'f7' + payload_raw_bytes.hex()
            try:
                if self.is_valid(payload_hexstring):                    
                    payload_dict = self._parse_payload(payload_hexstring)
                    self._publish_device_payload(client, payload_dict)
                else:
                    continue
            except Exception:
                client.publish(f"{ROOT_TOPIC_NAME}/dev/error", payload_hexstring, qos=1, retain=True)

    def _process_command_message(self, client, msg):
        topic_split = msg.topic.split('/')
        # print(topic_split)
        # print(msg.payload)
        try:            
            # 예외처리 - 전열교환기 pesentage가 0일 경우, 전원으로 치환
            if topic_split[2]=="전열교환기" and topic_split[3]=="percentage" and topic_split[4]=="set" and msg.payload==b'0':
                topic_split[3]="power"
                msg.payload = b'OFF'
            
            device = self.get_device(device_name=topic_split[2])
            if len(device.child_devices)>0:
                payload = device.get_command_payload(topic_split[3], msg.payload.decode(),child_name=topic_split[2])
            else:
                payload = device.get_command_payload(topic_split[3], msg.payload.decode())
                
            # print(payload)
            client.publish(f"{ROOT_TOPIC_NAME}/dev/command", payload, qos=2, retain=False)
        except ValueError as e:
            print(e)
            client.publish(f"{ROOT_TOPIC_NAME}/dev/error", f"Error: {str(e)}", qos=1, retain=True)

    def _parse_payload(self, payload_hexstring):
        return re.match(r'f7(?P<device_id>0e|12|32|33|36)(?P<device_subid>[0-9a-f]{2})(?P<message_flag>[0-9a-f]{2})(?:[0-9a-f]{2})(?P<data>[0-9a-f]*)(?P<xor>[0-9a-f]{2})(?P<add>[0-9a-f]{2})', payload_hexstring).groupdict()

    def _publish_device_payload(self, client, payload_dict):
        # print(payload_dict)
        device = self.get_device(device_id=payload_dict['device_id'], device_subid=payload_dict['device_subid'])
        for topic, value in device.parse_payload(payload_dict).items():
            # print(topic)
            # print(value)
            client.publish(topic, value, qos=1, retain=False)

    def on_disconnect(self, client, userdata, rc):
        raise ConnectionError



# 새로운 Wallpad 클래스와 Device 클래스 정의
wallpad = Wallpad()

packet_2_payload_percentage = {'00': '0', '01': '1', '02': '2', '03': '3'}
packet_2_payload_oscillation = {'03': 'oscillate_on', '00': 'oscillation_off', '01': 'oscillate_off'}

# 전열교환기
optional_info = {'optimistic': 'false', 'speed_range_min': 1, 'speed_range_max': 3}
전열교환기 = wallpad.add_device(device_name='전열교환기', device_id='32', device_subid='01', device_class='fan', optional_info=optional_info)
전열교환기.register_status(message_flag='01', attr_name='availability', topic_class='availability_topic', regex=r'()', process_func=lambda v: 'online')
전열교환기.register_status(message_flag='81', attr_name='power', topic_class='state_topic', regex=r'00(0[01])0[0-3]0[013]00', process_func=lambda v: 'ON' if v == '01' else 'OFF')
전열교환기.register_status(message_flag='81', attr_name='percentage', topic_class='percentage_state_topic', regex=r'000[01](0[0-3])0[013]00', process_func=lambda v: packet_2_payload_percentage[v])
전열교환기.register_command(message_flag='41', attr_name='power', topic_class='command_topic', process_func=lambda v: '01' if v == 'ON' else '00')
전열교환기.register_command(message_flag='42', attr_name='percentage', topic_class='percentage_command_topic', process_func=lambda v: {payload: packet for packet, payload in packet_2_payload_percentage.items()}[v])

# 가스차단기
optional_info = {'optimistic': 'false'}
가스 = wallpad.add_device(device_name='가스', device_id='12', device_subid='01', device_class='switch', optional_info=optional_info)
가스.register_status(message_flag='01', attr_name='availability', topic_class='availability_topic', regex=r'()', process_func=lambda v: 'online')
가스.register_status(message_flag='81', attr_name='power', topic_class='state_topic', regex=r'0(0[02])0', process_func=lambda v: 'ON' if v == '02' else 'OFF')
가스.register_command(message_flag='41', attr_name='power', topic_class='command_topic', process_func=lambda v: '00' if v == 'ON' else '04')

# 조명
optional_info = {'optimistic': 'false'}
조명 = wallpad.add_device(device_name='조명', device_id='0e', device_subid='1f', child_devices = ["거실1", "거실2"], device_class='light', optional_info=optional_info)
조명.register_status(message_flag='81', attr_name='power', topic_class='state_topic', regex=r'0[01](0[01])(0[01])', process_func=lambda v: 'ON' if v == '01' else 'OFF')
조명.register_command(message_flag='41', attr_name='power', topic_class='command_topic', controll_id=['11','12'], process_func=lambda v: '01' if v == 'ON' else '00')

# 난방
optional_info = {'modes': ['off', 'heat',], 'temp_step': 1.0, 'precision': 1.0, 'min_temp': 10.0, 'max_temp': 40.0, 'send_if_off': 'false'}
난방 = wallpad.add_device(device_name='난방', device_id='36', device_subid='1f', child_devices = ["거실", "침실", "서재"], device_class='climate', optional_info=optional_info)

for message_flag in ['81', '01', ]:
    # 0007000000141619191619
    난방.register_status(message_flag, attr_name='power', topic_class='mode_state_topic', regex=r'00([0-9a-fA-F]{2})[0-9a-fA-F]{18}', process_func=lambda v: 'heat' if v != 0 else 'off')

    # 추가적인 상태 등록 (away_mode, targettemp 등)
    난방.register_status(message_flag=message_flag, attr_name='away_mode', topic_class='away_mode_state_topic', regex=r'00[0-9a-fA-F]{2}([0-9a-fA-F]{2})[0-9a-fA-F]{16}', process_func=lambda v: 'ON' if v != 0 else 'OFF')

    # 온도 관련 상태 등록
    난방.register_status(message_flag=message_flag, attr_name='currenttemp', topic_class='current_temperature_topic', regex=r'00[0-9a-fA-F]{10}([0-9a-fA-F]{2})[0-9a-fA-F]{2}([0-9a-fA-F]{2})[0-9a-fA-F]{2}([0-9a-fA-F]{2})', process_func=lambda v: int(v, 16))
    난방.register_status(message_flag=message_flag, attr_name='targettemp', topic_class='temperature_state_topic', regex=r'00[0-9a-fA-F]{8}([0-9a-fA-F]{2})[0-9a-fA-F]{2}([0-9a-fA-F]{2})[0-9a-fA-F]{2}([0-9a-fA-F]{2})[0-9a-fA-F]{2}', process_func=lambda v: int(v, 16))
    
    # 난방온도 설정 커맨드
    난방.register_command(message_flag='43', attr_name='power', topic_class='mode_command_topic', controll_id=['11','12','13'], process_func=lambda v: '01' if v == 'heat' else '00')
    난방.register_command(message_flag='44', attr_name='targettemp', topic_class='temperature_command_topic', controll_id=['11','12','13'], process_func=lambda v: hex(int(float(v)))[2:])
    난방.register_command(message_flag='45', attr_name='away_mode', topic_class='away_mode_command_topic', controll_id=['11','12','13'], process_func=lambda v: '01' if v =='ON' else '00')

# 엘리베이터
optional_info = {'modes': ['down']}
엘리베이터 = wallpad.add_device(device_name='엘리베이터', device_id='33', device_subid='01', device_class='switch', optional_info=optional_info)

엘리베이터.register_status(message_flag='44', attr_name='floor', topic_class='current_floor_state_topic', regex=r'([0-9a-fA-F]{2})', process_func=lambda v: int(v))
엘리베이터.register_status(message_flag='01', attr_name='availability', topic_class='availability_topic', regex=r'()', process_func=lambda v: 'online')
엘리베이터.register_status(message_flag='44', attr_name='power', topic_class='state_topic', regex=r'()', process_func=lambda v: 'ON')
엘리베이터.register_status(message_flag='57', attr_name='power', topic_class='state_topic', regex=r'()', process_func=lambda v: 'OFF')
엘리베이터.register_status(message_flag='D7', attr_name='power', topic_class='state_topic', regex=r'()', process_func=lambda v: 'OFF')
엘리베이터.register_command(message_flag='81', attr_name='power', topic_class='command_topic', process_func=lambda v: '24' if v == 'ON' else '00')

wallpad.listen()
