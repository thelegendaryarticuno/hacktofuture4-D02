from flask import Flask, jsonify


app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})

#just a deployment check for second time

@app.get("/user")
def user():
    return jsonify({"id": 1, "name": "demo-user"})


@app.get("/order")
def order():
    return jsonify({"order_id": 1001, "status": "created"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)