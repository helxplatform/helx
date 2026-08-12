import { Request, Response, NextFunction } from 'express'
import type { WebSocket } from 'ws'
import { IWebsocketEvents, WebsocketEvents } from '../events'

interface Clients {
    [remoteUser: string]: IWebsocketEvents
}
interface GetClient {
    (remoteUser: string): IWebsocketEvents
}
interface AddClient {
    (remoteUser: string, ws: WebSocket): void
}
interface DeleteClient {
    (remoteUser: string, ws: WebSocket): void
}

const clients: Clients = {}
/**
 * Get the event emitter instance. If it doesn't exist yet, create one for the client without any websockets attached.
 */
const getClient: GetClient = (remoteUser: string) => {
    if (!clients[remoteUser]) clients[remoteUser] = new WebsocketEvents()
    return clients[remoteUser]
}
/**
 * Attach a websocket connection to a client.
 */
const addClient: AddClient = (remoteUser: string, ws: WebSocket) => {
    if (!clients[remoteUser]) clients[remoteUser] = new WebsocketEvents()
    clients[remoteUser].addWebsocket(ws)
}
/**
 * Detach a websocket connection from a client.
 */
const deleteClient: DeleteClient = (remoteUser: string, ws: WebSocket) => {
    if (clients[remoteUser]) {
        clients[remoteUser].removeWebsocket(ws)
    }
}

declare global {
    namespace Express {
        interface Request {
            getWsClient?: GetClient,
            addWsClient?: AddClient,
            deleteWsClient?: DeleteClient
        }
    }
}

export default (req: Request, res: Response, next: NextFunction) => {
    req.getWsClient = getClient
    req.addWsClient = addClient
    req.deleteWsClient = deleteClient
    next()
}