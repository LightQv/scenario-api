const express = require("express");
const cors = require("cors");
const cookieParser = require("cookie-parser");
const router = require("./router");

//--- Express app ---//
const app = express();

//--- Middlewares ---//
app.use(
  cors({
    origin: process.env.FRONTEND_URL,
    optionsSuccessStatus: 200,
    credentials: true,
  })
);

app.use(express.json());
app.use(cookieParser());

//--- Call API Routes ---//
app.use(router);

module.exports = app;
