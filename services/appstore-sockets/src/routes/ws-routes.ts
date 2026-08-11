import { Router } from  'express'
import expressWs from 'express-ws'
import { WsReadyEvent } from '../events/ws-ready-event'
import { appstoreIdentityMiddleware } from '../middleware'

const router = Router()
expressWs(router as any)

router.use(appstoreIdentityMiddleware)

router.ws('/', (ws, req) => {
    let { appstoreIdentity } = req
    const { remoteUser } = appstoreIdentity!
    const addWsClient = req.addWsClient!
    const deleteWsClient = req.deleteWsClient!
    const getWsClient = req.getWsClient!

    console.log(`Websocket connection opened by client ${ remoteUser }`)
    addWsClient(remoteUser, ws)

    // Appstore identity middleware is async, which means the websocket server is unable to receive messages
    // despite being in an open state until the middleware completes and verifies the connection.
    // Therefore, clients should wait until receiving a _confirmReady before sending messages.
    ws.send(JSON.stringify(new WsReadyEvent().serialize()))

    ws.on('message', (msg: string) => {
        let eventType, eventData
        try {
            ({
                type: eventType,
                ...eventData
            } = JSON.parse(msg))
        } catch (e) {
            console.error('Could not parse message as JSON: ', msg)
            return
        }
        console.log(`Handling event ${ eventType } with following parameters: ${ JSON.stringify(eventData) }`)
        switch (eventType) {
            case "initial_app_statuses":
                getWsClient(remoteUser).emitInitialAppStatuses()
                break
            case "clear_logs":
                getWsClient(remoteUser).clearLogs()
                break
            default:
                console.log(`Unrecognized event ${ eventType }`)
        }
    })
    ws.on('close', (code, reason) => {
        console.log(`Websocket connection closed by client ${ remoteUser }, code: ${ code}, reason: ${ reason }`)
        deleteWsClient(remoteUser, ws)
    })
})

export default router