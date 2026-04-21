const express = require('express');
const app = express();

// Mount OS routes
app.use('/api/os', require('./os/status'));

// Mount Jarvis routes
app.use('/api/jarvis', require('./jarvis'));

module.exports = app;