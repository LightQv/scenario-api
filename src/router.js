const express = require("express");

const router = express.Router();

const {
  hashPassword,
  logout,
  verifyPassword,
  verifyToken,
} = require("./services/auth");
const {
  generatePasswordToken,
  getUserByEmailMiddleware,
  verifyPasswordToken,
} = require("./controllers/authControllers");
const {
  addUser,
  deleteUser,
  editUserPw,
  getUser,
  editUserBanner,
  editUserMail,
  getUserBanner,
  editUser,
} = require("./controllers/userControllers");
const { validatePw, validateUser } = require("./services/validators");
const { sendForgottenPassword } = require("./services/nodemailer");
const {
  addView,
  deleteView,
  viewByUser,
} = require("./controllers/viewControllers");
const {
  addWatchlist,
  deleteWatchlist,
  watchlistByUser,
  watchlistDetails,
  editWatchlist,
} = require("./controllers/watchlistControllers");
const { addMedia, deleteMedia } = require("./controllers/mediaControllers");

//--- Public Routes ---//
router.post("/api/v1/auth/register", validateUser, hashPassword, addUser);
router.post("/api/v1/auth/login", getUserByEmailMiddleware, verifyPassword);
router.post(
  "/api/v1/auth/forgotten-password",
  getUserByEmailMiddleware,
  generatePasswordToken,
  sendForgottenPassword
);
router.post(
  "/api/v1/auth/reset-password",
  verifyPasswordToken,
  validatePw,
  hashPassword,
  editUserPw
);
router.get("/auth/logout", logout);

//--- Private Routes (Require Auth) ---//
router.use(verifyToken); /* Middleware wall to verify if the user got a Token */

// User's Update & Delete
router.get("/api/v1/user/:id", getUser);
router.get("/api/v1/user/banner/:id", getUserBanner);
router.put("/api/v1/user/:id", validateUser, hashPassword, editUser);
router.put("/api/v1/user/banner/:id", editUserBanner);
router.put("/api/v1/user/email/:id", editUserMail);
router.delete("/api/v1/user/:id", deleteUser);

// Watchlist CRUD
router.get("/api/v1/user/watchlist/:id", watchlistByUser);
router.get("/api/v1/user/watchlist/detail/:id", watchlistDetails);
router.post("/api/v1/watchlist", addWatchlist);
router.put("/api/v1/watchlist/:id", editWatchlist);
router.delete("/api/v1/watchlist/:id", deleteWatchlist);

// Media Create & Delete
router.post("/api/v1/media", addMedia);
router.delete("/api/v1/media/:id", deleteMedia);

// View Create, Read & Delete
router.get("/api/v1/user/view/:type/:id", viewByUser);
router.post("/api/v1/view", addView);
router.delete("/api/v1/view/:id", deleteView);

module.exports = router;
