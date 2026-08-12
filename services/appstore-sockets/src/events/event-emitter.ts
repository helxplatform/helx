import type { WebSocket } from 'ws'
import type { IEvent } from './event'
import { AppStatusEvent, InitialAppStatusesEvent, AppStatus, ContainerStatus, AppStatusData } from './app-status-events'

export interface IWebsocketEvents {
    addWebsocket(ws: WebSocket): void
    removeWebsocket(ws: WebSocket): void
    clearLogs(): void


    emitInitialAppStatuses(): void
    emitAppStatus(appStatusData: AppStatusData): void
}

export class WebsocketEvents implements IWebsocketEvents {
    // Support multiple connections to the same "client"
    private websockets: WebSocket[] = []
    private eventLogs: IEvent<any>[] = []
    
    constructor() {}

    private emit<T>(event: IEvent<T>) {
        console.log(`Emitting ${ event.getType() } event (${ this.websockets.length } receivers)`)
        this.eventLogs.push(event)
        this.websockets.forEach((ws) => ws.send(JSON.stringify(event.serialize())))
    }
    
    public addWebsocket(ws: WebSocket) {
        this.websockets.push(ws)
    }
    public removeWebsocket(ws: WebSocket) {
        this.websockets = this.websockets.filter((_ws) => _ws !== ws)
    }

    public clearLogs() {
        this.eventLogs = []
    }

    public emitInitialAppStatuses() {
        const event = new InitialAppStatusesEvent(this.eventLogs.filter((event) => event.getType() === AppStatusEvent.TYPE) as AppStatusEvent[])
        this.emit(event)
    }

    public emitAppStatus(
        appStatusData: AppStatusData
    ) {
        const event = new AppStatusEvent(appStatusData)
        this.emit(event)
    }
}