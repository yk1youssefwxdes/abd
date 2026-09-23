from django.template.loaders.filesystem import Loader as FilesystemLoader
from django.template import TemplateDoesNotExist

def xor_crypt(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

class DecryptedFilesystemLoader(FilesystemLoader):
    def get_contents(self, origin):
        try:
            with open(origin.name, 'rb') as fp:
                encrypted_data = fp.read()
            if encrypted_data.startswith(b'ENC\x00'):
                key = b'WjUPGJkCB3rBU65JxLlhQlSJ0cmgIYiEwZjz9bT8+7Y='
                decrypted_data = xor_crypt(encrypted_data[4:], key)
                return decrypted_data.decode(self.engine.file_charset)
            else:
                return encrypted_data.decode(self.engine.file_charset)
        except FileNotFoundError:
            raise TemplateDoesNotExist(origin)

