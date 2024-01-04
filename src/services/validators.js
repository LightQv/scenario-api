const Joi = require("joi");

// Schema for new User
const userSchema = Joi.object({
  username: Joi.string().min(5).max(30).required().messages({
    "any.required": "Username is required",
    "string.min": "Username must contain min 5 characters",
    "string.max": "Username must contain max 30 characters",
  }),
  email: Joi.string()
    .email({
      minDomainSegments: 2,
      tlds: { allow: ["com", "net", "fr"] },
    })
    .max(255)
    .required()
    .messages({
      "any.required": "Email is required",
      "string.max": "Email must contain max 255 characters",
      "string.email": "Email must be in a valid form",
    }),
  password: Joi.string().min(7).max(30).required().messages({
    "any.required": "Password is required",
    "string.min": "Password must contain min 8 characters",
    "string.max": "Password must contain max 30 characters",
  }),
  confirmPassword: Joi.any()
    .equal(Joi.ref("password"))
    .required()
    .label("Confirm password")
    .messages({ "any.only": "{{#label}} does not match" }),
});

const validateUser = (req, res, next) => {
  const { username, email, password, confirmPassword } = req.body;

  const { error } = userSchema.validate(
    { username, email, password, confirmPassword },
    { abortEarly: false }
  );

  if (!error) {
    next();
  } else res.status(422).json({ validationErrors: error?.details });
};

// Schema for new Password
const validatePwSchema = Joi.object({
  password: Joi.string().min(7).max(30).required().messages({
    "any.required": "Password is required",
    "string.min": "Password must contain min 8 characters",
    "string.max": "Password must contain max 30 characters",
  }),
  confirmPassword: Joi.any()
    .equal(Joi.ref("password"))
    .required()
    .label("Confirm password")
    .messages({ "any.only": "{{#label}} does not match" }),
});

const validatePw = (req, res, next) => {
  const { password, confirmPassword } = req.body;

  const { error } = validatePwSchema.validate(
    { password, confirmPassword },
    { abortEarly: false }
  );

  if (!error) {
    next();
  } else res.status(422).json({ validationErrors: error?.details });
};

module.exports = { validateUser, validatePw };
