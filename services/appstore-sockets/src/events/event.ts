import { v4 as uuidv4 } from 'uuid'

// A JSON-serializable representation of an IEvent
interface SerializedEvent {
    uid: string
    type: string
    timestamp: number
    data: string | number | boolean | any[] | object
}
export interface IEvent<T> {
    getUid(): string
    getType(): string
    getTimestamp(): number
    getData(): T
    serialize(): SerializedEvent
}
export abstract class Event<T> implements IEvent<T> {
    private static uidCache: string[] = []

    private readonly type: string
    private readonly uid: string
    private readonly timestamp: number
    private readonly data: T
    constructor(type: string, data: T) {
        this.type = type
        this.uid = Event.generateUid()
        this.timestamp = Date.now() / 1000
        this.data = data
    }
    private static generateUid(): string {
        let uid = uuidv4()
        while (this.uidCache.includes(uid)) {
            uid = uuidv4()
        }
        this.uidCache.push(uid)
        return uid
    }

    getType() { return this.type }
    getUid() { return this.uid }
    getTimestamp() { return this.timestamp }
    getData() { return this.data }
    serialize() { 
        return {
            uid: this.getUid(),
            type: this.getType(),
            timestamp: this.getTimestamp(),
            data: this.getData() as unknown as object
        }
    }
}