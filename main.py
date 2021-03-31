from tqdm.auto import tqdm
import os
import json
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2 import service_account
from googleapiclient.discovery import build
from io import BytesIO
import requests


class GoogleDriveUploader:
    SCOPES = ['https://www.googleapis.com/auth/drive']

    def __init__(self, credentials_file_name):
        """Конструктор класса GoogleDriveUploader.
           Примет путь к файлу с ключами сервисного аккаунта Google.
           """
        self.class_name = 'Google Drive'
        self.SERVICE_ACCOUNT_FILE = credentials_file_name
        self.max_number_photos = 5
        self.credentials = service_account.Credentials.from_service_account_file(
            self.SERVICE_ACCOUNT_FILE, scopes=self.SCOPES)
        self.service = build('drive', 'v3', credentials=self.credentials)
        results = self.service.files().list(pageSize=10,
                                            q='sharedWithMe = True',
                                            fields="nextPageToken, files(id, name, permissions,  mimeType)").execute()
        self.shared_folder_id = results['files'][0]['id']
        permissions = results['files'][0]['permissions']
        for permission in permissions:
            if permission['role'] == 'owner':
                self.name = permission['emailAddress']

    def find_object_by_name(self, name, parent_folder, type_of_object):
        """ Найдет и возвратит список обьектов на Google Drive,
        Примет имя обьекта, ID папки, в которой искать, его тип - 'file' или 'folder'Б
        """
        query = {'folder': f"and mimeType = 'application/vnd.google-apps.folder'",
                 'file': f"and mimeType='image/jpeg'"}
        response = self.service.files().list(spaces='drive',
                                             q=f"name = '{name}' and '{parent_folder}'"
                                               f" in parents {query[type_of_object]}",
                                             fields="nextPageToken, files(id, name)").execute()
        return response['files']

    def createFolder(self, folder_name, parent_folder_id):
        """Создаст папку на Google Drive.
         Примет имя и ID родительской папки.
         """
        response = self.service.files().list(spaces='drive',
                                             q=f"name = '{folder_name}' and '{parent_folder_id}' in parents "
                                               f"and mimeType = 'application/vnd.google-apps.folder'",
                                             fields="nextPageToken, files(id, name)").execute()
        if len(self.find_object_by_name(folder_name, parent_folder_id, 'folder')) == 0:
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [parent_folder_id]
            }
            result = self.service.files().create(body=file_metadata, fields='id').execute()
            return result['id']
        else:
            return response['files'][0]['id']

    def upload(self, photos, folder, subfolder, album_name=None, number_photos=None):
        """Примет список словарей в формате {'file_name', 'size', 'url'}.
        Загрузит заданное количество number_photos на Google Drive: folder/subfolder/album_name.
        Создаст json-файл с информацией по файлу по адресу: ./folder/subfolder/album_name/metadata.json"""
        folder_id = self.createFolder(folder, self.shared_folder_id)
        subfolder_id = self.createFolder(subfolder, folder_id)
        if album_name is None:
            parent_folder_id = subfolder_id
            parent_folder_path = f"{folder}/{subfolder}"
        else:
            parent_folder_id = self.createFolder(album_name, subfolder_id)
            parent_folder_path = f"{folder}/{subfolder}/{album_name}"
        if number_photos is None:
            number = self.max_number_photos
        else:
            number = number_photos

        for photo in tqdm(photos[:number], ncols=100, desc=f"Loading {'profile' if album_name is None else album_name}"
                                                           f"...", unit='Kb'):
            existed_files = self.find_object_by_name(photo['file_name'], parent_folder_id, 'file')
            if len(existed_files) != 0:
                self.service.files().delete(fileId=existed_files[0]['id']).execute()

            response = requests.get(photo['url'])
            fh = BytesIO(response.content)
            media_body = MediaIoBaseUpload(fh, mimetype='image/jpeg',
                                           chunksize=1024 * 1024, resumable=True)
            file_metadata = {
                'name': photo['file_name'],
                'uploadType': 'media',
                'parents': [parent_folder_id]
            }
            self.service.files().create(body=file_metadata, media_body=media_body, fields='id').execute()
        print('Успешная загрузка на Google Drive!')
        metadata = get_list_metadata(photos[:number])
        write_metadata(metadata, parent_folder_path)


class YandexUploader:
    url = 'https://cloud-api.yandex.net/v1/disk'

    def __init__(self, ya_token):
        """Конструктор класса YandexUploader.
           Примет токен с Полигона Яндекс Диска.
           """
        self.token = ya_token
        self.class_name = 'Яндекс Диск'
        self.headers = {'Authorization': f'OAuth {self.token}'}
        self.name = requests.get(self.url, params={'fields': 'user'}, headers=self.headers).json()["user"][
            "display_name"]
        self.max_number_photos = 5

    def createFolder(self, path):
        """Создаст папку на Яндекс Диск по заданному пути path."""
        url = 'https://cloud-api.yandex.net/v1/disk/resources'
        headers = {'Authorization': f'OAuth {self.token}'}
        params = {'path': path}
        folder_request = requests.get(url, params=params, headers=headers)
        if folder_request.status_code != 200:
            folder_response = requests.put(url, params=params, headers=headers)
            folder_response.raise_for_status()

    def upload(self, photos, folder, subfolder, album_name=None, number_photos=None):
        """Примет список словарей в формате {'file_name', 'size', 'url'},
        Загрузит заданное количество number_photos на Яндекс Диск: folder/subfolder/album_name.
        Создаст json-файл с информацией по файлу по адресу: ./folder/subfolder/album_name/metadata.json"""
        url = "https://cloud-api.yandex.net/v1/disk/resources/upload"
        headers = {'Authorization': f'OAuth {self.token}'}
        self.createFolder(folder)
        self.createFolder(f"{folder}/{subfolder}")
        if album_name is None:
            path = f"{folder}/{subfolder}"
        else:
            path = f"{folder}/{subfolder}/{album_name}"
            self.createFolder(path)
        if number_photos is None:
            number = self.max_number_photos
        else:
            number = number_photos
        for photo in tqdm(photos[:number], ncols=100, desc=f"Loading {'profile' if album_name is None else album_name}"
                                                           f"...", unit='Kb'):
            response = requests.get(
                url,
                params={
                    "path": f"{path}/{photo['file_name']}",
                    'overwrite': True
                },
                headers=headers
            )
            href = response.json()["href"]
            photo_response = requests.get(photo['url'])
            upload_response = requests.put(href, data=photo_response.content)
            upload_response.raise_for_status()
        metadata = get_list_metadata(photos[:number])
        write_metadata(metadata, path)
        return print('Успешная загрузка на Яндекс Диск!')


class Vk:
    url = 'https://api.vk.com/method/'

    def __init__(self, vk_token, version):
        """Конструктор класса Vk.
        Примет токен аккаунта VK, номер версии.
        """
        self.token = vk_token
        self.class_name = 'VKontakte'
        self.version = version
        self.params = {
            'access_token': self.token,
            'v': self.version
        }

    def targetUserExists(self, target_id):
        """Проверит, есть ли доступ к аккаунту с target_id"""
        users_info_url = self.url + 'users.get'
        users_info_params = {
            'user_ids': target_id
        }
        response = requests.get(users_info_url, params={**self.params, **users_info_params})
        try:
            return response.json()['response']
        except KeyError:
            print(response.json()['error']['error_msg'])
            return False


class VkUser(Vk):
    def __init__(self, vk_token, version, target_id):
        """Конструктор класса VkUser.
        Примет токен аккаунта VK, номер версии и ID искомого пользователя.
        """
        super().__init__(vk_token, version)
        self.params = {
            'access_token': self.token,
            'v': self.version,
            'user_ids': target_id
        }
        self.target_id = target_id
        self.target_first_name = requests.get(self.url + 'users.get', self.params).json()['response'][0]['first_name']
        self.target_last_name = requests.get(self.url + 'users.get', self.params).json()['response'][0]['last_name']
        self.target_name = f"{self.target_first_name} {self.target_last_name}"

    def getPhotos(self, owner_id, album_id=None):
        """Возвратит список значений 'items' обьекта response.
        Примет ID пользоватееля VK и ID альбома"""
        users_photos_url = self.url + 'photos.get'
        if album_id is None:
            album_id = 'profile'
        users_photos_params = {
            'owner_id': owner_id,
            'album_id': album_id,
            'extended': 1,
            'photo_sizes': 1
        }
        items = []
        response = requests.get(users_photos_url, params={**self.params, **users_photos_params})
        try:
            items = response.json()['response']['items']
        except KeyError:
            print(response.json()['error']['error_msg'])
        return items

    def getAlbumsInfo(self, owner_id):
        """Возвратит список ID и названий альбомов пользоватееля VK.
        Примет ID пользоватееля"""
        albums = []
        users_albums_url = self.url + 'photos.getAlbums'
        users_albums_params = {
            'owner_id': owner_id
        }
        response = requests.get(users_albums_url, params={**self.params, **users_albums_params})
        try:
            items = response.json()['response']['items']
        except KeyError:
            print(response.json()['error']['error_msg'])
            return albums
        for item in items:
            albums.append({'id': item['id'], 'title': item['title']})
        return albums


class Insta:
    def __init__(self, token, version):
        """Конструктор класса Insta.
        Примет токен аккаунта Instagram Graph API и номер версии.
        """
        self.url = f"https://graph.facebook.com/{version}/"
        self.access_token = token
        self.class_name = 'Instagram'
        self.params = {
            'access_token': self.access_token,
            'fields': 'instagram_business_account'
        }
        self.page_id = requests.get(self.url + 'me/accounts', self.params).json()['data'][0]['id']
        self.instagram_account_id = \
            requests.get(self.url + self.page_id + '/', self.params).json()['instagram_business_account']['id']

    def targetUserExists(self, target_ig_username):
        """Проверит, есть ли доступ к аккаунту с именем target_ig_username"""
        self.params['fields'] = f"business_discovery.username({target_ig_username})"
        url = self.url + self.instagram_account_id
        response = requests.get(url, self.params)
        try:
            return response.status_code == 200
        except KeyError:
            print(response.json()['error']['message'])
            return False


class InstaUser(Insta):
    def __init__(self, token, version, target_ig_username):
        """Конструктор класса InstaUser, наследник от Insta.
        Примет токен аккаунта Instagram Graph API, номер версии и имя искомого пользователя
        """
        super().__init__(token, version)
        self.url = f"https://graph.facebook.com/{version}/{self.instagram_account_id}/"
        self.params['fields'] = f"business_discovery.username({target_ig_username})" \
                                f"{{username,ig_id,id,media_count,profile_picture_url}}"
        self.target_media_count = requests.get(self.url, self.params).json()['business_discovery']['media_count']
        self.target_name = target_ig_username
        self.profile_picture_url = \
            requests.get(self.url, self.params).json()['business_discovery']['profile_picture_url']

    def getPhotos(self):
        """Возвратит список значений 'data' медафайлов пользователя Instagram"""
        self.params['fields'] = f"business_discovery.username({self.target_name})" \
                                f"{{media{{media_type,timestamp,media_url,like_count}}}}"
        photos = \
            requests.get(self.url, self.params).json()['business_discovery']['media']['data']
        return photos


def vk_get_list_for_load(items):
    """Примет список обьектов фотографий пользователя VK.
    Возвратит список словарей с ключами {'file_name', 'size', 'url'}.
    """
    photos_metadata = []
    file_name_list = []
    for item in items:
        file_name = f"{str(item['likes']['count'])}.jpg"
        if file_name in file_name_list:
            file_name = f"{str(item['likes']['count'])}{str(item['date'])}.jpg"
        size = item['sizes'][-1]['type']
        url = item['sizes'][-1]['url']
        file_name_list.append(file_name)
        album_id = item['album_id']
        photos_metadata.append({'album_id': album_id, 'file_name': file_name, 'size': size, 'url': url})
    return photos_metadata


def ig_get_list_for_load(medias):
    """Примет список обьектов фотографий пользователя Instagram.
    Возвратит список словарей с ключами {'file_name', 'size', 'url'}.
    """
    photos_metadata = []
    file_name_list = []
    for media in medias:
        if media['media_type'] == 'IMAGE':
            file_name = f"{str(media['like_count'])}.jpg"
            if file_name in file_name_list:
                file_name = f"{str(media['like_count'])}{str(media['timestamp'])}.jpg"
            file_name_list.append(file_name)
            photos_metadata.append({'album_id': 'Media', 'file_name': file_name,
                                    'size': 'IMAGE', 'url': media['media_url']})
    return photos_metadata


def get_list_metadata(photos):
    """Примет список словарей с ключами {'file_name', 'size', 'url'}.
    Возвратит список словарей с ключами {'file_name', 'size'}.
    """
    metadata = []
    for photo in photos:
        metadata.append({'file_name': photo['file_name'], 'size': photo['size']})
    return metadata


def write_metadata(metadata, file_path):
    """Примет список словарей с ключами {'file_name', 'size'} и путь к файлу с метаданными file_path.
    Создаст json-файл с информацией по файлу по адресу file_path.
    """
    work_path = os.getcwd()
    path_for_write = f"{work_path}/{file_path}"
    if not os.path.exists(path_for_write):
        os.makedirs(path_for_write)
    with open(f"{path_for_write}/metadata.json", "w", encoding="utf-8") as file:
        json.dump(metadata, file)
    print(f"Путь к файлу с метаданными: "
          f"./{file_path}/metadata.json")
    print(metadata)
    print()


def input_command(commands_desc, step, nb_albums, media_choice=None):
    """Возвратит команду пользователя, если она есть в списке доступных команд.
    Примет список команд, шаг вызова, количество альбомов, выбор социальной сети: v=VK или i=Instagram.
    """
    if nb_albums != 0 and media_choice == 'v':
        commands_desc['s'] = f"select users album from {nb_albums}"
    elif nb_albums != 0 and media_choice == 'i':
        commands_desc['a'] = f"all medias ({nb_albums})"
    message = ['Команда не определена. Введите команду из списка:',
               'Введите команду: ',
               'Из какой социальной сети сохранить фото?',
               f"Выберите, что загрузить:"]
    value = ''
    while value not in commands_desc.keys():
        print(message[step])
        step = 0
        for key in commands_desc:
            print(key, '-', commands_desc[key])
        value = input().lower()
    return value


def input_token(command):
    """Возвратит токен или путь к файлу.
    Примет выбор загрузчика: y=Яндекс Диск или g=Google Drive.
    """
    if command == 'y':
        message = 'Введите токен для Яндекс Диска: '
        value = input(message)
    elif command == 'g':
        message = 'Введите путь к service_account_file пользователя: '
        value = input(message)
    else:
        value = 'Ошибка'
    return value


def create_yandex_uploader(ya_token):
    """Создаст и возвратит обьект класса YandexUploader.
    Примет токен с Полигона Яндекс Диска.
    """
    # with open('ya_token.txt', 'r') as file_object:
    #     my_yandex_token = file_object.read().strip()
    # uploader = YandexUploader(my_yandex_token)
    uploader = YandexUploader(ya_token)
    return uploader


def create_google_uploader(credentials_file_name):
    """Создаст и возвратит обьект класса GoogleDriveUploader.
    Примет путь к service_account_file пользователя Google.
    """
    # uploader = GoogleDriveUploader('credentials.json')
    uploader = GoogleDriveUploader(credentials_file_name)
    return uploader


def vk_create_user():
    """Спросит ID искомого пользователя VK, создаст и возвратит обьект класса VkUser.
    Необходим рабочий токен пользователя VK API в файле vk_token.txt корневого каталога.
    """
    with open('vk_token.txt', 'r') as file_object:
        my_vk_token = file_object.read().strip()
    vk = Vk(my_vk_token, '5.130')
    while True:
        target_id = input('Введите ID пользователя VK: ')
        if vk.targetUserExists(target_id):
            return VkUser(my_vk_token, '5.130', target_id)


def ig_create_user():
    """Спросит username искомого пользователя Instagram, создаст и возвратит обьект класса InstaUser.
    Необходим рабочий токен аккаунта Instagram Graph API в файле instagram_token.txt корневого каталога.
    """
    with open('instagram_token.txt', 'r') as file_object:
        my_instagram_token = file_object.read().strip()
    insta = Insta(my_instagram_token, 'v10.0')
    while True:
        target_ig_username = input('Введите Instagram username: ')
        if insta.targetUserExists(target_ig_username):
            return InstaUser(my_instagram_token, 'v10.0', target_ig_username)


def vk_upload_album(uploader, media, album_id, album_name=None):
    """Загрузит альбом пользователя VK.
    Примет обьект класса загрузки, обьект класса VKUser, id альбома, название альбома.
    """
    photos = vk_get_list_for_load(media.getPhotos(media.target_id, album_id))
    if len(photos) == 0:
        print(f"В альбоме нет доступных фото.\n")
    elif len(photos) > uploader.max_number_photos:
        uploader.upload(photos, media.class_name, media.target_name, album_name,
                        input_number_for_download(album_id if album_name is None else album_name, len(photos)))
    else:
        uploader.upload(photos, media.class_name, media.target_name, album_name)


def vk_upload_all_albums(uploader, media):
    """Загрузит все альбомы пользователя VK.
    Примет обьект класса загрузки и обьект класса VKUser.
    """
    vk_upload_profile_photos(uploader, media)
    vk_upload_wall_photos(uploader, media)
    album_list = media.getAlbumsInfo(media.target_id)
    if len(album_list) != 0:
        for album in album_list:
            vk_upload_album(uploader, media, album['id'], album['title'])


def vk_upload_wall_photos(uploader, media):
    """Вызовет метод загрузки альбома wall пользователя VK.
    Примет обьект класса загрузки и обьект класса VKUser.
    """
    vk_upload_album(uploader, media, 'wall', 'wall')


def vk_upload_profile_photos(uploader, media):
    """Вызовет метод загрузки альбома profile пользователя VK.
    Примет обьект класса загрузки и обьект класса VKUser.
    """
    vk_upload_album(uploader, media, 'profile')


def input_number_for_download(album_name, photos_count):
    """Возвратит число фотографий для загрузки.
    Примет название альбома и количество фотографий в альбоме.
    """
    while True:
        number = input(f"В альбоме {album_name} {photos_count} доступных фото. Сколько загрузить?")
        if not (number.isnumeric()) or int(number) > photos_count or int(number) == 0:
            print('Введите числовое значение')
        else:
            return int(number)


def vk_input_album(album_list):
    """Возвратит команду выбора альбома.
    Примет список альбомов пользователя VK.
    """
    commands = dict()
    message = ['Команда не определена. Введите команду из списка',
               'Выберите альбом']
    for i, album in enumerate(album_list):
        commands[str(i + 1)] = album
    step = 1
    value = ''
    while value not in commands.keys():
        print(message[step])
        step = 0
        for i, album in enumerate(album_list):
            print(i + 1, '-', album['title'])
        value = input().lower()
    return commands[value]


def vk_upload_selected_album(uploader, media):
    """Проверит есть ли доступные альбомы пользователя VK и вызовет методы выбора и загрузки альбома.
    Примет обьект класса загрузки, обьект класса VKUser.
    """
    album_list = media.getAlbumsInfo(media.target_id)
    print(album_list)
    if len(album_list) != 0:
        selected_album = vk_input_album(album_list)
        vk_upload_album(uploader, media, selected_album['id'], selected_album['title'])


def get_media_count(media_profile):
    """Возвратит количество альбомов VK или фотографий пользователя Instagram.
    Примет обьект класса VKUser или InstaUser.
    """
    if media_profile.class_name == 'VKontakte':
        return len(media_profile.getAlbumsInfo(media_profile.target_id))
    elif media_profile.class_name == 'Instagram':
        return media_profile.target_media_count


def ig_upload_all_photos(uploader, media):
    """Вызовет методы загрузки всех доступных медиафайлов пользователя Instagram.
    Примет обьект класса загрузки и обьект класса InstaUser.
    """
    ig_upload_profile_photo(uploader, media)
    photos = ig_get_list_for_load(media.getPhotos())
    if len(photos) == 0:
        print(f"Нет доступных фото.\n")
    elif len(photos) > uploader.max_number_photos:
        uploader.upload(photos, media.class_name, media.target_name, 'Media',
                        input_number_for_download('Media', len(photos)))
    else:
        uploader.upload(photos, media.class_name, media.target_name, 'Media')


def ig_upload_profile_photo(uploader, media):
    """Вызовет метод загрузки фотографии профиля пользователя Instagram.
    Примет обьект класса загрузки и обьект класса InstaUser.
    """
    photo = [{'album_id': 'profile', 'file_name': 'profile_photo', 'size': 'profile',
              'url': f"{media.profile_picture_url}"}]
    uploader.upload(photo, media.class_name, media.target_name)


def main():
    storage = {'commands': {'y': create_yandex_uploader,
                            'g': create_google_uploader},
               'description': {'y': 'Yandex Disc',
                               'g': 'Google Drive',
                               'q': 'quit'}}

    media = {'commands': {'v': vk_create_user,
                          'i': ig_create_user},
             'description': {'v': 'VKontakte',
                             'i': 'Instagram',
                             'q': 'quit (назад)'}}

    albums = {'commands': {'v': {'a': vk_upload_all_albums,
                                 'p': vk_upload_profile_photos,
                                 'w': vk_upload_wall_photos,
                                 's': vk_upload_selected_album},
                           'i': {'a': ig_upload_all_photos,
                                 'p': ig_upload_profile_photo}
                           },
              'description': {'v': {'a': 'all',
                                    'p': 'profile album',
                                    'w': 'wall album',
                                    'q': 'quit (назад)'},
                              'i': {'a': 'all media',
                                    'p': 'profile photo',
                                    'q': 'quit (назад)'}
                              }}

    while True:
        user_storage_choice = input_command(storage['description'], 1, 0)
        if user_storage_choice != 'q':
            user_token = input_token(user_storage_choice)
            while True:
                user_media_choice = input_command(media['description'], 2, 0)
                if user_media_choice != 'q':
                    uploader_profile = storage['commands'][user_storage_choice](user_token)
                    media_profile = media['commands'][user_media_choice]()
                    print(f"\nПрофиль: {media_profile.target_name} ({media_profile.class_name})"
                          f" ==> Профиль: {uploader_profile.name} ({uploader_profile.class_name})")
                    while True:
                        user_album_choice = \
                            input_command(albums['description'][user_media_choice], 3,
                                          get_media_count(media_profile), user_media_choice)
                        if user_album_choice != 'q':
                            albums['commands'][user_media_choice][user_album_choice](uploader_profile, media_profile)
                        else:
                            break
                else:
                    break
        else:
            print('До свидания!')
            break


if __name__ == "__main__":
    main()
