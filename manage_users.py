import bcrypt
import sqlite3

def connect_db():
    return sqlite3.connect('portfolio.db')

def add_user(username, password):
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    conn = connect_db()
    c = conn.cursor()
    c.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, password_hash))
    conn.commit()
    conn.close()

if __name__ == '__main__':
    # Interactive script to add users
    username = input("Enter username: ")
    password = input("Enter password: ")
    add_user(username, password)
    print("User added successfully.")
