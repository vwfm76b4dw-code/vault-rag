#include <bits/stdc++.h>
using namespace std;
int n=0;
int main()
{
	for(int i=10000;i<=99999;i++){
		n++;
		if(i%81==0&&i%91==0){
			if((i/100)%10==1){
				cout<<i<<endl;
				break;
			}
		}
	}
	cout<<n;
}
