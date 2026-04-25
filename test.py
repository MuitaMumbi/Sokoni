import mysql.connector


try:
    # Establish connection
    mydb = mysql.connector.connect(
        host="localhost",      # Or your server's IP address
        user="root",   # Default is often "root"
        password="MySQL1234",
        database="yourdatabase"
    )

    if mydb.is_connected():
        print("Successfully connected to the database")
        
        # Create a cursor to execute queries
        cursor = mydb.cursor()
        cursor.execute("SELECT DATABASE();")
        record = cursor.fetchone()
        print("You are connected to database:", record)

except mysql.connector.Error as err:
    print(f"Error: {err}")

finally:
    # Always close the connection
    if 'mydb' in locals() and mydb.is_connected():
        cursor.close()
        mydb.close()
        print("MySQL connection is closed")
