import { Card } from '../components/Card'
import { TextLink } from '../components/TextLink'
import { HOME_HREF } from '../routes'
import { PageLayout } from './PageLayout'

/** Any address the app has no page for: says so, and leads back home. */
export function NotFoundPage() {
  return (
    <PageLayout>
      <Card className="flex flex-col items-center gap-4 text-center">
        <h1 className="text-3xl text-primary sm:text-4xl">Page not found</h1>
        <p className="text-muted">There is nothing at this address.</p>
        <TextLink href={HOME_HREF} className="self-center">
          Back to the start
        </TextLink>
      </Card>
    </PageLayout>
  )
}
