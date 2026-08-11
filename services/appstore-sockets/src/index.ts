import path from 'path'
import express from 'express'
import expressWs from 'express-ws'
import morgan from 'morgan'
import bodyParser from 'body-parser'
import cookieParser from 'cookie-parser'
import expressListRoutes from 'express-list-routes'
import { wsClientMiddleware } from './middleware'
import { wsRouter, eventRouter } from './routes'

const app = express()
expressWs(app)

app.use(morgan('tiny'))
app.use(bodyParser.json())
app.use(cookieParser())
app.use(wsClientMiddleware)

app.use('/ws', wsRouter)
app.use('/hooks', eventRouter)

app.get('/routes', (req, res) => {
    res.json(expressListRoutes(app))
})

app.listen(5555, () => console.log("Listening on port 5555"))