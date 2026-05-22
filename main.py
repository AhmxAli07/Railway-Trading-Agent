from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "🚂 Hello from Railway! My app is working!"

@app.route("/about")
def about():
    return "This is my first Railway deployment!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
