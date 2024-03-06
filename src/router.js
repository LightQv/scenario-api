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
  countViewByYear,
  viewByType,
  countViewByType,
  runtimeViewByUser,
} = require("./controllers/viewControllers");
const {
  addWatchlist,
  deleteWatchlist,
  watchlistByUser,
  watchlistDetails,
  editWatchlist,
} = require("./controllers/watchlistControllers");
const {
  addMedia,
  deleteMedia,
  editMedia,
} = require("./controllers/mediaControllers");

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
router.get("/api/v1/auth/logout", logout);

//--- Private Routes (Require Auth) ---//
router.use(verifyToken); /* Middleware wall to verify if the user got a Token */

// User's Read, Update & Delete
router.get("/api/v1/users/:id", getUser);
router.get("/api/v1/users/banner/:id", getUserBanner);
router.put("/api/v1/users/:id", validateUser, hashPassword, editUser);
router.put("/api/v1/users/banner/:id", editUserBanner);
router.put("/api/v1/users/email/:id", editUserMail);
router.put("/api/v1/users/password/:id", validatePw, hashPassword, editUserPw);
router.delete("/api/v1/users/:id", deleteUser);

// Watchlist CRUD
router.get("/api/v1/watchlists/:id", watchlistByUser);
router.get("/api/v1/watchlists/detail/:id", watchlistDetails);
router.post("/api/v1/watchlists", addWatchlist);
router.put("/api/v1/watchlists/:id", editWatchlist);
router.delete("/api/v1/watchlists/:id", deleteWatchlist);

// Media Create, Update & Delete
router.post("/api/v1/medias", addMedia);
router.put("/api/v1/medias/:id", editMedia);
router.delete("/api/v1/medias/:id", deleteMedia);

// View Create, Read & Delete
router.get("/api/v1/views/:type/:id", viewByType);
router.get("/api/v1/views/:id", viewByUser);
router.post("/api/v1/views", addView);
router.delete("/api/v1/views/:id", deleteView);

// Statistics Read
router.get("/api/v1/stats/count/:type/:id", countViewByType);
router.get("/api/v1/stats/runtime/:type/:id", runtimeViewByUser);
router.get("/api/v1/stats/year/:type/:id", countViewByYear);

module.exports = router;
