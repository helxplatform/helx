import { Request, Response, NextFunction } from 'express'

interface AuthenticationMiddleware {
    (req: Request, res: Response, next: NextFunction): void
}

export default function(authSecret: string): AuthenticationMiddleware {
    return (req: Request, res: Response, next: NextFunction) => {
        const auth = req.headers.authorization
        const isValid = auth === `Basic ${ authSecret }`
        if (isValid) {
            next()
        } else {
            res.status(401)
            res.send(
                'You haven\'t provided valid credentials to access this resource'
            )
        }
    }
}