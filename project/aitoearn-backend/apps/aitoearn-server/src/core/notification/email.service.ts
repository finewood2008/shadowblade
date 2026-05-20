import type { Locale } from '@yikart/common'
import { Injectable, Logger } from '@nestjs/common'
import { NotificationType } from '@yikart/common'
import { MailService } from '@yikart/mail'
import { ContentGenerationTaskStatus } from '@yikart/mongodb'

@Injectable()
export class EmailService {
  logger = new Logger(EmailService.name)
  constructor(
    private readonly mailService: MailService,
  ) { }

  async sendAgentResultEmail(
    mail: string,
    taskId: string,
    status: ContentGenerationTaskStatus,
    description: string,
    locale: Locale = 'en-US',
  ): Promise<boolean> {
    const isZh = locale === 'zh-CN'
    try {
      return this.mailService.sendEmail({
        to: mail,
        subject: isZh ? `火花 代理任务结果：${status}` : `火花 Agent ${status}`,
        template: isZh ? 'mail/agent-zh' : 'mail/agent',
        context: {
          taskId,
          status,
          description,
        },
      })
    }
    catch (error) {
      this.logger.error(error)
      return false
    }
  }

  async sendTaskNotificationEmail(
    mail: string,
    title: string,
    content: string,
    type: NotificationType,
    locale: Locale = 'en-US',
  ): Promise<boolean> {
    const isZh = locale === 'zh-CN'
    try {
      return this.mailService.sendEmail({
        to: mail,
        subject: isZh ? `火花：${title}` : `火花: ${title}`,
        template: isZh ? 'mail/task-notification-zh' : 'mail/task-notification',
        context: {
          title,
          content,
          type,
        },
      })
    }
    catch (error) {
      this.logger.error(error)
      return false
    }
  }
}
