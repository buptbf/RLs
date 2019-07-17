import numpy as np
import tensorflow as tf
from Algorithms.algorithm_base import Policy


initKernelAndBias = {
    'kernel_initializer': tf.random_normal_initializer(0., .1),
    'bias_initializer': tf.constant_initializer(0.1, dtype=tf.float32)
}


class SAC(Policy):
    def __init__(self,
                 s_dim,
                 visual_sources,
                 visual_resolutions,
                 a_dim_or_list,
                 action_type,
                 alpha=0.2,
                 auto_adaption=True,
                 gamma=0.99,
                 ployak=0.995,
                 lr=5.0e-4,
                 max_episode=50000,
                 batch_size=100,
                 buffer_size=10000,
                 cp_dir=None,
                 log_dir=None,
                 excel_dir=None,
                 logger2file=False,
                 out_graph=False):
        super().__init__(s_dim, visual_sources, visual_resolutions, a_dim_or_list, action_type, max_episode, cp_dir, 'OFF', batch_size, buffer_size)
        self.gamma = gamma
        self.ployak = ployak
        with self.graph.as_default():
            self.sigma_offset = tf.placeholder(tf.float32, [self.a_counts, ], 'sigma_offset')

            self.log_alpha = tf.get_variable('log_alpha', dtype=tf.float32, initializer=0.0)
            self.alpha = alpha if not auto_adaption else tf.exp(self.log_alpha)

            self.lr = tf.train.polynomial_decay(lr, self.episode, self.max_episode, 1e-10, power=1.0)

            self.norm_dist, self.a_new, self.log_prob = self._build_actor_net('actor_net')
            tf.identity(self.mu, 'action')
            self.entropy = self.norm_dist.entropy()
            self.s_a = tf.concat((self.s, self.pl_a), axis=1)
            self.s_a_new = tf.concat((self.s, self.a_new), axis=1)
            self.q1 = self._build_q_net('q1', self.s_a, False)
            self.q2 = self._build_q_net('q2', self.s_a, False)
            self.q1_anew = self._build_q_net('q1', self.s_a_new, True)
            self.q2_anew = self._build_q_net('q2', self.s_a_new, True)
            self.v_from_q = tf.minimum(self.q1_anew, self.q2_anew) - self.alpha * self.log_prob
            self.v_from_q_stop = tf.stop_gradient(self.v_from_q)
            self.v, self.v_var = self._build_v_net('v', input_vector=self.s, trainable=True)
            self.v_target, self.v_target_var = self._build_v_net('v_target', input_vector=self.s_, trainable=False)
            self.dc_r = tf.stop_gradient(self.pl_r + self.gamma * self.v_target)

            self.q1_loss = tf.reduce_mean(tf.squared_difference(self.q1, self.dc_r))
            self.q2_loss = tf.reduce_mean(tf.squared_difference(self.q2, self.dc_r))
            self.v_loss = tf.reduce_mean(tf.squared_difference(self.v, self.v_from_q))
            self.v_loss_stop = tf.reduce_mean(tf.squared_difference(self.v, self.v_from_q_stop))
            self.critic_loss = 0.5 * self.q1_loss + 0.5 * self.q2_loss + 0.5 * self.v_loss_stop
            self.actor_loss = -tf.reduce_mean(self.q1_anew - self.alpha * self.log_prob)
            self.alpha_loss = -tf.reduce_mean(self.log_alpha * tf.stop_gradient(self.log_prob - self.a_counts))

            q1_vars = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope='q1')
            q2_vars = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope='q2')
            value_vars = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope='v')
            actor_vars = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope='actor_net')

            optimizer = tf.train.AdamOptimizer(self.lr)
            self.train_q1 = optimizer.minimize(self.q1_loss, var_list=q1_vars)
            self.train_q2 = optimizer.minimize(self.q2_loss, var_list=q2_vars)
            self.train_v = optimizer.minimize(self.v_loss, var_list=value_vars)

            self.assign_v_target = tf.group([tf.assign(r, self.ployak * v + (1 - self.ployak) * r) for r, v in zip(self.v_target_var, self.v_var)])
            # self.assign_v_target = [tf.assign(r, 1/(self.episode+1) * v + (1-1/(self.episode+1)) * r) for r, v in zip(self.v_target_var, self.v_var)]
            with tf.control_dependencies([self.assign_v_target]):
                self.train_critic = optimizer.minimize(self.critic_loss, var_list=q1_vars + q2_vars + value_vars + self.conv_vars, global_step=self.global_step)
            with tf.control_dependencies([self.train_critic]):
                self.train_actor = optimizer.minimize(self.actor_loss, var_list=actor_vars + self.conv_vars)
            with tf.control_dependencies([self.train_actor]):
                self.train_alpha = optimizer.minimize(self.alpha_loss, var_list=[self.log_alpha])

            tf.summary.scalar('LOSS/actor_loss', tf.reduce_mean(self.actor_loss))
            tf.summary.scalar('LOSS/critic_loss', tf.reduce_mean(self.critic_loss))
            tf.summary.scalar('LOSS/entropy', tf.reduce_mean(self.entropy))
            tf.summary.scalar('LEARNING_RATE/lr', tf.reduce_mean(self.lr))
            self.summaries = tf.summary.merge_all()
            self.generate_recorder(
                cp_dir=cp_dir,
                log_dir=log_dir,
                excel_dir=excel_dir,
                logger2file=logger2file,
                graph=self.graph if out_graph else None
            )
            self.recorder.logger.info('''
　　　　ｘｘｘｘｘｘｘ　　　　　　　　　　　ｘｘ　　　　　　　　　　　ｘｘｘｘｘｘ　　　　
　　　　ｘｘ　　　ｘｘ　　　　　　　　　　ｘｘｘ　　　　　　　　　　ｘｘｘ　　ｘｘ　　　　
　　　　ｘｘ　　　　ｘ　　　　　　　　　　ｘｘｘ　　　　　　　　　　ｘｘ　　　　ｘｘ　　　
　　　　ｘｘｘｘ　　　　　　　　　　　　　ｘ　ｘｘ　　　　　　　　　ｘｘ　　　　　　　　　
　　　　　ｘｘｘｘｘｘ　　　　　　　　　ｘｘ　ｘｘ　　　　　　　　ｘｘｘ　　　　　　　　　
　　　　　　　　ｘｘｘ　　　　　　　　　ｘｘｘｘｘｘ　　　　　　　ｘｘｘ　　　　　　　　　
　　　　ｘ　　　　ｘｘ　　　　　　　　ｘｘ　　　ｘｘ　　　　　　　　ｘｘ　　　　ｘｘ　　　
　　　　ｘｘ　　　ｘｘ　　　　　　　　ｘｘ　　　ｘｘ　　　　　　　　ｘｘｘ　　ｘｘｘ　　　
　　　　ｘｘｘｘｘｘｘ　　　　　　　ｘｘｘ　　ｘｘｘｘｘ　　　　　　　ｘｘｘｘｘｘ　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　
            ''')
            self.init_or_restore(cp_dir)

    def _build_actor_net(self, name):
        with tf.variable_scope(name):
            actor1 = tf.layers.dense(
                inputs=self.s,
                units=128,
                activation=self.activation_fn,
                name='actor1',
                **initKernelAndBias
            )
            actor2 = tf.layers.dense(
                inputs=actor1,
                units=64,
                activation=self.activation_fn,
                name='actor2',
                **initKernelAndBias
            )
            self.mu = tf.layers.dense(
                inputs=actor2,
                units=self.a_counts,
                activation=tf.nn.tanh,
                name='mu',
                **initKernelAndBias
            )
            sigma1 = tf.layers.dense(
                inputs=actor1,
                units=64,
                activation=self.activation_fn,
                name='simga1',
                **initKernelAndBias
            )
            self.sigma = tf.layers.dense(
                inputs=sigma1,
                units=self.a_counts,
                activation=tf.nn.sigmoid,
                name='sigma',
                **initKernelAndBias
            )
            norm_dist = tf.distributions.Normal(loc=self.mu, scale=self.sigma + self.sigma_offset)
            # action = tf.tanh(norm_dist.sample())
            action = tf.clip_by_value(norm_dist.sample(), -1, 1)
            log_prob = norm_dist.log_prob(action)
        return norm_dist, action, log_prob

    def _build_q_net(self, name, input_vector, reuse):
        with tf.variable_scope(name):
            layer1 = tf.layers.dense(
                inputs=input_vector,
                units=256,
                activation=self.activation_fn,
                name='layer1',
                reuse=reuse,
                **initKernelAndBias
            )
            layer2 = tf.layers.dense(
                inputs=layer1,
                units=256,
                activation=self.activation_fn,
                name='layer2',
                reuse=reuse,
                **initKernelAndBias
            )
            q = tf.layers.dense(
                inputs=layer2,
                units=1,
                activation=None,
                name='q_value',
                reuse=reuse,
                **initKernelAndBias
            )
        return q

    def _build_v_net(self, name, input_vector, trainable):
        with tf.variable_scope(name):
            layer1 = tf.layers.dense(
                inputs=input_vector,
                units=256,
                activation=self.activation_fn,
                name='layer1',
                trainable=trainable,
                **initKernelAndBias
            )
            layer2 = tf.layers.dense(
                inputs=layer1,
                units=256,
                activation=self.activation_fn,
                name='layer2',
                trainable=trainable,
                **initKernelAndBias
            )
            v = tf.layers.dense(
                inputs=layer2,
                units=1,
                activation=None,
                name='value',
                trainable=trainable,
                **initKernelAndBias
            )
            var = tf.get_variable_scope().global_variables()
        return v, var

    def choose_action(self, s):
        pl_visual_s, pl_s = self.get_visual_and_vector_input(s)
        return self.sess.run(self.a_new, feed_dict={
            self.pl_visual_s: pl_visual_s,
            self.pl_s: pl_s,
            self.sigma_offset: np.full(self.a_counts, 0.01)
        })

    def choose_inference_action(self, s):
        pl_visual_s, pl_s = self.get_visual_and_vector_input(s)
        return self.sess.run(self.mu, feed_dict={
            self.pl_visual_s: pl_visual_s,
            self.pl_s: pl_s,
            self.sigma_offset: np.full(self.a_counts, 0.01)
        })

    def store_data(self, s, a, r, s_, done):
        self.off_store(s, a, r[:, np.newaxis], s_, done[:, np.newaxis])

    def learn(self, episode):
        s, a, r, s_, _ = self.data.sample()
        pl_visual_s, pl_s = self.get_visual_and_vector_input(s)
        pl_visual_s_, pl_s_ = self.get_visual_and_vector_input(s_)
        # self.sess.run([self.assign_v_target, self.train_q1, self.train_q2, self.train_v, self.train_actor], feed_dict={
        #     self.pl_visual_s: pl_visual_s,
        #     self.pl_s: pl_s,
        #     self.pl_a: a,
        #     self.pl_r: r,
        #     self.pl_visual_s_: pl_visual_s_,
        #     self.pl_s_: pl_s_,
        #     self.episode: episode,
        #     self.sigma_offset: np.full(self.a_counts, 0.01)
        # })
        summaries, _ = self.sess.run([self.summaries, [self.assign_v_target, self.train_critic, self.train_actor, self.train_alpha]], feed_dict={
            self.pl_visual_s: pl_visual_s,
            self.pl_s: pl_s,
            self.pl_a: a,
            self.pl_r: r,
            self.pl_visual_s_: pl_visual_s_,
            self.pl_s_: pl_s_,
            self.episode: episode,
            self.sigma_offset: np.full(self.a_counts, 0.01)
        })
        self.recorder.writer.add_summary(summaries, self.sess.run(self.global_step))
