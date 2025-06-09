import pymysql
import pandas as pd
from config import Config
import streamlit as st
from typing import Optional

class Database:
    def __init__(self):
        self.config = Config()
        self.connection = None
        self._connect()
        

    def _connect(self):
        try:
            self.connection = pymysql.connect(
                host=self.config.DB_HOST,
                user=self.config.DB_USER,
                password=self.config.DB_PASS,
                database=self.config.DB_NAME,
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=True
            )
        except pymysql.Error as e:
            st.error(f"Database connection failed: {e}")
            st.stop()


    def _ensure_connection(self):
        if not self.connection or not self.connection.open:
            self._connect()


    def execute_query(self, query, params=None, return_result=True):
        """Универсальный метод выполнения запросов"""
        self._ensure_connection()
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, params or ())
                
                if return_result and query.strip().upper().startswith('SELECT'):
                    result = cursor.fetchall()
                    return pd.DataFrame(result) if result else pd.DataFrame()
                
                # Для INSERT/UPDATE/DELETE возвращаем количество затронутых строк
                return cursor.rowcount
                
        except pymysql.Error as e:
            st.error(f"Database error: {e}")
            return None
        

    # Методы для работы с пользователями
    def get_emploee(self, login):
        query = "SELECT * FROM users WHERE login = %s"
        result = self.execute_query(query, (login,))
        return result.iloc[0].to_dict() if not result.empty else None
    
    
    def get_analyst_user(self, login):
        """Получение только администраторов"""
        query = "SELECT * FROM users WHERE login = %s AND id_role = %s"
        return self.execute_query(query, (login, self.config.ADMIN_ROLE_ID))
    

    def create_emploee(self, login, email, password, role_id=1):
        """Создание нового пользователя"""
        # Сначала проверяем, нет ли уже такого пользователя
        if self.get_emploee(login):
            st.error("Пользователь с таким логином уже существует")
            return False
            
        query = """
        INSERT INTO users (login, email, password_hash, id_role, created_at)
        VALUES (%s, %s, %s, %s, NOW())
        """
        affected_rows = self.execute_query(
            query, 
            (login, email, self._hash_password(password), role_id),
            return_result=False
        )
        return affected_rows == 1
    
    
    def get_last_classification_id(self, id_user: int) -> Optional[int]:
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    SELECT c.id
                    FROM classifications c
                    JOIN documents d ON c.id_document = d.id
                    WHERE d.id_user = %s
                    ORDER BY c.created_at DESC
                    LIMIT 1
                """, (id_user,))
                row = cursor.fetchone()
                return row["id"] if row else None
        except pymysql.Error as e:
            st.error(f"Ошибка при получении последней классификации: {e}")
            return None


    def create_rating(self, classification_id: int, id_user: int, rating: int, comment: str = "") -> bool:
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO ratings (id_classification, id_user, rating, comment, created_at)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (classification_id, id_user, rating, comment))
                return True
        except pymysql.Error as e:
            st.error(f"Ошибка при сохранении рейтинга: {e}")
            return False

    
    def create_analyst_user(self, login, email, password):
        """Создание администратора (без проверки ключа)"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO users (login, email, password_hash, id_role, created_at) " \
                    "VALUES (%s, %s, %s, 2, NOW())",
                    (login, email, self._hash_password(password)))
                return cursor.rowcount == 1
        except pymysql.Error as e:
            st.error(f"Ошибка создания администратора: {e}")
            return False
        
        
    def create_zip_folder(self, id_user: int, foldername: str, count_files: int) -> Optional[int]:
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO folders_zip (id_user, foldername, count_files, uploaded_at)
                    VALUES (%s, %s, %s, NOW())
                    """,
                    (id_user, foldername, count_files)
                )
                return cursor.lastrowid
        except pymysql.Error as e:
            st.error(f"Ошибка при создании записи архива: {e}")
            return None
        
        
    # Новый метод для классификации файла из архива
    def create_archive_classification(self, id_user: int, filename: str, model_name: str, 
                                   predicted_class: str, confidence: float, id_folder_zip: int) -> Optional[int]:
        """Создает запись о классификации файла из архива"""
        try:
            with self.connection.cursor() as cursor:
                # Создаем запись о документе с привязкой к архиву
                cursor.execute(
                    """
                    INSERT INTO documents (id_user, filename, id_folder_zip, uploaded_at)
                    VALUES (%s, %s, %s, NOW())
                    """,
                    (id_user, filename, id_folder_zip)
                )
                doc_id = cursor.lastrowid

                # Создаем запись о классификации
                cursor.execute(
                    """INSERT INTO classifications 
                       (id_document, model_used, predicted_class, confidence, created_at)
                       VALUES (%s, %s, %s, %s, NOW())""",
                    (doc_id, model_name, predicted_class, confidence)
                )
                self.connection.commit()
                return cursor.lastrowid
        except pymysql.Error as e:
            st.error(f"Ошибка при сохранении классификации из архива: {e}")
            return None
        
    
    # Новый метод для обновления счетчика файлов в архиве
    def update_zip_file_count(self, folder_zip_id: int, new_count: int) -> bool:
        """Обновляет количество файлов в архиве"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE folders_zip SET count_files = %s WHERE id = %s",
                    (new_count, folder_zip_id)
                )
                self.connection.commit()
                return cursor.rowcount > 0
        except pymysql.Error as e:
            st.error(f"Ошибка при обновлении счетчика файлов архива: {e}")
            return False
        

    # Методы для работы с классификациями
    def create_classification(self, id_user, filename, model_name, predicted_class, confidence) -> Optional[int]:
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO documents (id_user, filename, uploaded_at) VALUES (%s, %s, NOW())",
                    (id_user, filename)
                )
                doc_id = cursor.lastrowid

                cursor.execute(
                    """INSERT INTO classifications 
                       (id_document, model_used, predicted_class, confidence, created_at)
                       VALUES (%s, %s, %s, ROUND(%s, 2), NOW())""",
                    (doc_id, model_name, predicted_class, confidence)
                )
                return cursor.lastrowid
        except pymysql.Error as e:
            st.error(f"Ошибка при сохранении классификации: {e}")
            return None
        

    def get_emploee_history(self, id_user):
        """Получение истории классификаций пользователя"""
        query = """
        SELECT 
            d.filename as filename,
            c.model_used as model_used,
            c.predicted_class as predicted_class,
            c.confidence as confidence,
            c.created_at as created_at,
			r.rating as rating,
			r.comment as comment_user
        FROM classifications c
        JOIN documents d ON c.id_document = d.id
		LEFT JOIN ratings r ON c.id = r.id_classification
        WHERE d.id_user = %s
        ORDER BY c.created_at DESC
        """
        return self.execute_query(query, (id_user,))


    def get_all_classifications(self):
        """Получение всех классификаций (для админа)"""
        query = """
        SELECT 
            u.login, 
            d.filename, 
            c.model_used, 
            c.predicted_class,
            c.confidence,
            c.created_at,
            r.rating,
            r.comment
        FROM classifications c
        JOIN documents d ON c.id_document = d.id
        JOIN users u ON d.id_user = u.id
        LEFT JOIN ratings r ON r.id_classification = c.id
        ORDER BY c.created_at DESC
        """
        return self.execute_query(query)
    

    def emploee_exists(self, login, email):
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM users WHERE login = %s OR email = %s LIMIT 1",
                (login, email)
            )
            return cursor.fetchone() is not None


    def _hash_password(self, password: str) -> str:
        """Хеширование пароля"""
        import hashlib
        return hashlib.sha256(password.encode()).hexdigest()