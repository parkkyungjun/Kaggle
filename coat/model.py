from kaggle_hubmap_kv3 import *
from daformer import *
from coat import *

class RGB(nn.Module):
	IMAGE_RGB_MEAN = [0.485, 0.456, 0.406]  # [0.5, 0.5, 0.5]
	IMAGE_RGB_STD = [0.229, 0.224, 0.225]  # [0.5, 0.5, 0.5]
	
	def __init__(self, ):
		super(RGB, self).__init__()
		self.register_buffer('mean', torch.zeros(1, 3, 1, 1))
		self.register_buffer('std', torch.ones(1, 3, 1, 1))
		self.mean.data = torch.FloatTensor(self.IMAGE_RGB_MEAN).view(self.mean.shape)
		self.std.data = torch.FloatTensor(self.IMAGE_RGB_STD).view(self.std.shape)
	
	def forward(self, x):
		x = (x - self.mean) / self.std
		return x



def init_weight(m):
    classname = m.__class__.__name__
    if classname.find('Conv') != -1:
        nn.init.kaiming_normal_(m.weight, mode='fan_in', nonlinearity='relu')
        #nn.init.orthogonal_(m.weight, gain=1)
        if m.bias is not None:
            m.bias.data.zero_()
    elif classname.find('Batch') != -1:
        m.weight.data.normal_(1,0.02)
        m.bias.data.zero_()
    elif classname.find('Linear') != -1:
        nn.init.orthogonal_(m.weight, gain=1)
        if m.bias is not None:
            m.bias.data.zero_()
    elif classname.find('Embedding') != -1:
        nn.init.orthogonal_(m.weight, gain=1)

def init_model():
    encoder = coat_parallel_small_plus()
    checkpoint = '../input/hubmapsmall/coat_small_7479cf9b.pth'
    checkpoint = torch.load(checkpoint, map_location=lambda storage, loc: storage)
    state_dict = checkpoint['model']
    encoder.load_state_dict(state_dict,strict=False)

    model = Net(encoder=encoder).cuda()
    
    return model

class Net(nn.Module):
	# def load_pretrain( self,):
	# 	path =  '/home/jupyter/share/WRQ/Hubmap/input/coat_lite_medium/coat_lite_medium_384x384_f9129688.pth'
	# 	checkpoint = torch.load(path, map_location=lambda storage, loc: storage)
	# 	self.state_dict = checkpoint['model']
	# 	self.encoder.load_state_dict(checkpoint,strict=False)


	def __init__(self,
	             
	             decoder=daformer_conv1x1,
				 encoder=coat_parallel_small_plus,
	             encoder_cfg={},
	             decoder_cfg={},
	             ):  # decoder = daformer_conv3x3,   for coat-medium
		super(Net, self).__init__()
		decoder_dim = decoder_cfg.get('decoder_dim', 320)
		
		# ----
		self.output_type = ['inference', 'loss']
		

		self.rgb = RGB()

		self.encoder = encoder
		
		encoder_dim = self.encoder.embed_dims
		
		self.decoder = decoder(
			encoder_dim=encoder_dim,
			decoder_dim=decoder_dim,
		)
		self.logit = nn.Sequential(
			nn.Conv2d(decoder_dim, 1, kernel_size=1),
		)

		self.aux = nn.ModuleList([
            nn.Conv2d(decoder_dim, 1, kernel_size=1, padding=0) for i in range(4)
        ])
		self.avgpool = nn.AdaptiveAvgPool2d((1,1))
		# self.cls_head = nn.Linear(320,5,bias = False)
		self.cls_head = nn.Sequential(
							nn.BatchNorm1d(320).apply(init_weight),
							nn.Linear(320, 128 ).apply(init_weight),
							
							nn.ReLU(inplace=True),
							nn.BatchNorm1d(128).apply(init_weight),
							nn.Linear(128, 5).apply(init_weight)
						)
	 
	

	def forward(self, batch):
		
		x = batch['image']
		
		num_class = 5


		x = self.rgb(x)
		
		B, C, H, W = x.shape

        
		encoder = self.encoder(x)

		last, decoder = self.decoder(encoder)

		logit = self.logit(last)
		logit = F.interpolate(logit, size=None, scale_factor=4, mode='bilinear', align_corners=False)

		output = {}
		if 'loss' in self.output_type:
			output['bce_loss'] = F.binary_cross_entropy_with_logits(logit,batch['mask'])
			# pdb.set_trace()
			# output["label_loss"] = F.nll_loss(F.log_softmax(cls_feature,dim=1), label)
			# output["label_loss"] = nn.CrossEntropyLoss()(cls_feature,label)
			for i in range(4):
				output['aux%d_loss'%i] = criterion_aux_loss(self.aux[i](decoder[i]),batch['mask'])
		if 'inference' in self.output_type:
			probability_from_logit = torch.sigmoid(logit)
			output['probability'] = probability_from_logit
		
		return output

def criterion_aux_loss(logit, mask):
    mask = F.interpolate(mask,size=logit.shape[-2:], mode='nearest')
    loss = F.binary_cross_entropy_with_logits(logit,mask)
    return loss



