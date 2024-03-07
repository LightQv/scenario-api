# SCENARIO

What do I watch tonight ?! Good question, right ?!
Here's the API of [Scenario](https://scenario.vivianquerenet.com/), my website based on TMDB API to help you find something to watch for tonight.

## Languages & Tools
![NodeJS](https://img.shields.io/badge/node.js-6DA55F?style=for-the-badge&logo=node.js&logoColor=white)

![Express.js](https://img.shields.io/badge/express.js-%23404d59.svg?style=for-the-badge&logo=express&logoColor=%2361DAFB)

![Postgres](https://img.shields.io/badge/postgres-%23316192.svg?style=for-the-badge&logo=postgresql&logoColor=white)

![Prisma](https://img.shields.io/badge/Prisma-3982CE?style=for-the-badge&logo=Prisma&logoColor=white)

![Supabase](https://img.shields.io/badge/Supabase-3ECF8E?style=for-the-badge&logo=supabase&logoColor=white)

## Installation

Fork the project.

Use the package manager [npm](https://www.npmjs.com/) to install every dependencies.

```bash
npm install
```
Complete *.env* file with your own environment variables.
For your database, you need to use Postgres.

Then use the following command to build Prisma's schema.

```javascript
npm run build
```

Followed by :

```javascript
npm run migrate
```

Once the migration is successfully done, you'll be able to run the server.

## Usage

Launch the server locally with :

```javascript
npm run dev
``` 

Now you can login with the default user :
```javascript
#Email
email.toto@gmail.com

#Password
bladerunner
``` 

Or create you're **own**.

## Then ?

Visit the [client repository](https://github.com/LightQv/scenario-web-client) for instruction on how to run the client side locally.
